import tkinter as tk
from tkinter import filedialog, ttk, messagebox, simpledialog
import subprocess
import os
import json
from datetime import datetime, timedelta
import re
import threading
import time
import glob # Importar glob para encontrar ficheiros
import sys # Importar sys para forçar o flush do stdout

ARQ_PERFIS = "perfis.json"
DIAS_MANTER_LOGS = 30 # Número de dias para manter os arquivos de log

def verificar_rclone():
    """Verifica se o rclone está instalado e acessível no sistema."""
    try:
        subprocess.run(["rclone", "--version"], stdout=subprocess.DEVNULL, check=True)
        return True
    except:
        return False

def listar_pastas_onedrive():
    """Lista as pastas existentes no OneDrive usando rclone lsf."""
    try:
        resultado = subprocess.run(
            ["rclone", "lsf", "onedrive:", "--dirs-only"],
            capture_output=True, text=True, encoding="utf-8", check=True
        )
        pastas = [linha.strip().rstrip("/") for linha in resultado.stdout.splitlines() if linha.strip()]
        return pastas
    except Exception as e:
        print(f"Erro ao listar pastas do OneDrive: {e}")
        sys.stdout.flush() # Forçar a saída
        return []

def carregar_json(arquivo):
    """Carrega dados de um arquivo JSON."""
    if os.path.exists(arquivo):
        try:
            with open(arquivo, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            messagebox.showwarning("Erro no arquivo de perfis", "O arquivo de perfis está corrompido ou vazio. Criando um novo.")
            return {}
    return {}

def salvar_json(arquivo, conteudo):
    """Salva dados em um arquivo JSON."""
    with open(arquivo, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, indent=4, ensure_ascii=False)

def extrair_stats_completos(linha):
    """
    Extrai informações detalhadas de uma linha de estatísticas do rclone.
    Esta função foi aprimorada para capturar padrões de estatísticas
    tanto de linhas que começam com "Transferred:" quanto de linhas com "NOTICE:".
    Exemplo de linha do rclone (stats one line):
    Transferred:    10.345 MiB / 50.000 MiB, 20%, 1.234 MiB/s, ETA 00:40
    Exemplo de linha de dry-run (NOTICE):
    2025/07/07 15:46:16 NOTICE:     21.771 MiB / 21.771 MiB, 100%, 0 B/s, ETA -
    """
    # Regex mais flexível para capturar os valores de estatísticas
    # Adicionado (?:Transferred:|NOTICE:.*?\s*)? para capturar linhas que podem começar com "Transferred:" ou "NOTICE:"
    padrao = (
        r"(?:Transferred:|NOTICE:.*?\s*)?([\d\.]+) (MiB|B|KiB|GiB|TiB) / ([\d\.]+) (MiB|B|KiB|GiB|TiB),\s*([\d]+)%,.*?([\d\.]+) (MiB/s|B/s|KiB/s|GiB/s|TiB/s), ETA ([\d:-]+)"
    )
    match = re.search(padrao, linha)
    if match:
        transferido_val = float(match.group(1))
        transferido_unit = match.group(2)
        total_val = float(match.group(3))
        total_unit = match.group(4)
        porcentagem = int(match.group(5))
        velocidade_val = float(match.group(6))
        velocidade_unit = match.group(7)
        eta = match.group(8)

        # Normaliza para MiB para exibição consistente
        def convert_to_mib(value, unit):
            if unit == "B": return value / (1024 * 1024)
            if unit == "KiB": return value / 1024
            if unit == "MiB": return value
            if unit == "GiB": return value * 1024
            if unit == "TiB": return value * 1024 * 1024
            return value

        transferido_mib = convert_to_mib(transferido_val, transferido_unit)
        total_mib = convert_to_mib(total_val, total_unit)

        return f"{transferido_mib:.2f}", f"{total_mib:.2f}", str(porcentagem), f"{velocidade_val:.2f} {velocidade_unit}", eta
    return None, None, None, None, None

def validar_caminho(path):
    """
    Valida caracteres básicos em um caminho.
    Normaliza o caminho e lida com caracteres inválidos em nomes de arquivo.
    Permite caracteres acentuados e outros caracteres Unicode.
    """
    normalized_path = os.path.normpath(path)
    # Removido '+' do conjunto de caracteres inválidos
    invalid_chars_set = set('<>\"|?*#%&=@[]{}!`\'"')

    is_windows_drive_path = False
    if len(normalized_path) >= 2 and normalized_path[1] == ':' and normalized_path[0].isalpha():
        is_windows_drive_path = True

    for i, c in enumerate(normalized_path):
        if c == ':' and is_windows_drive_path and i == 1:
            continue
        if c == '/' or c == '\\':
            continue
        if ord(c) < 32 or ord(c) == 127:
            return False, f"caractere de controle ASCII (código: {ord(c)}) na posição {i}"
        if c in invalid_chars_set:
            return False, f"'{c}' (na posição {i})"
            
    return True, None

def limpar_logs_antigos(dias_manter):
    """
    Remove arquivos de log antigos do diretório atual.
    Arquivos com o padrão 'log_YYYY-MM-DD_HHhMM.txt' serão considerados.
    """
    hoje = datetime.now()
    for filename in os.listdir("."):
        if filename.startswith("log_") and filename.endswith(".txt"):
            try:
                data_str = filename[4:14]
                log_date = datetime.strptime(data_str, "%Y-%m-%d")
                if (hoje - log_date).days > dias_manter:
                    os.remove(filename)
                    print(f"Log antigo removido: {filename}")
                    sys.stdout.flush() # Forçar a saída
            except (ValueError, IndexError):
                continue
            except OSError as e:
                print(f"Erro ao remover log {filename}: {e}")
                sys.stdout.flush() # Forçar a saída


class CloudEaseApp:
    def __init__(self):
        self.processo = None
        self.sincronizando = False
        self.perfis = carregar_json(ARQ_PERFIS)

        limpar_logs_antigos(DIAS_MANTER_LOGS)

        self.janela = tk.Tk()
        self.janela.title("CloudEase")
        self.janela.geometry("650x850")
        self.janela.resizable(True, True)

        self.status_var = tk.StringVar(value="Pronto")
        self.modo_var = tk.StringVar(value="copy")

        self.velocidade_var = tk.StringVar(value="Velocidade: -")
        self.tempo_var = tk.StringVar(value="Tempo decorrido: 0m 0s")
        self.eta_var = tk.StringVar(value="ETA: -")
        self.transferido_var = tk.StringVar(value="Transferido: - / - MiB")
        self.progresso_var = tk.DoubleVar(value=0)

        self.setup_ui()

        if not verificar_rclone():
            messagebox.showerror("Erro", "⚠️ Rclone não está instalado ou não foi encontrado no sistema. Por favor, instale-o e configure-o para o OneDrive.")

        self.janela.mainloop()

    def setup_ui(self):
        main_frame = tk.Frame(self.janela, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=0)

        tk.Label(main_frame, text="📁 Pasta local:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(10, 0))
        self.entrada_origem = tk.Entry(main_frame, width=70)
        self.entrada_origem.grid(row=1, column=0, sticky="ew", pady=5)
        self.btn_escolher_pasta_local = tk.Button(main_frame, text="Escolher pasta", command=self.escolher_pasta_local, relief=tk.RAISED, bd=2)
        self.btn_escolher_pasta_local.grid(row=1, column=1, sticky="e", padx=(5,0))

        tk.Label(main_frame, text="☁️ Pasta remota no OneDrive:", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(15, 0))
        self.combo_onedrive = ttk.Combobox(main_frame, values=listar_pastas_onedrive(), width=60, state="readonly")
        self.combo_onedrive.grid(row=3, column=0, sticky="ew", pady=5)
        self.btn_atualizar_pastas_remotas = tk.Button(main_frame, text="🔄 Atualizar pastas remotas", command=self.atualizar_combo_onedrive, relief=tk.RAISED, bd=2)
        self.btn_atualizar_pastas_remotas.grid(row=3, column=1, sticky="e", padx=(5,0))

        self.btn_criar_pasta_onedrive = tk.Button(main_frame, text="➕ Criar nova pasta no OneDrive", command=self.criar_nova_pasta_onedrive, relief=tk.RAISED, bd=2)
        self.btn_criar_pasta_onedrive.grid(row=4, column=0, columnspan=2, pady=5)

        tk.Label(main_frame, text="🔄 Modo de operação:", font=("Segoe UI", 10, "bold")).grid(row=5, column=0, sticky="w", pady=(15, 0), columnspan=2)
        self.radio_copy = tk.Radiobutton(main_frame, text="Copiar (seguro)", variable=self.modo_var, value="copy", font=("Segoe UI", 9))
        self.radio_copy.grid(row=6, column=0, sticky="w")
        self.radio_sync = tk.Radiobutton(main_frame, text="Sincronizar (espelha e apaga)", variable=self.modo_var, value="sync", font=("Segoe UI", 9))
        self.radio_sync.grid(row=7, column=0, sticky="w")

        tk.Label(main_frame, text="📶 Limite de banda upload (Mbps):", font=("Segoe UI", 10, "bold")).grid(row=8, column=0, sticky="w", pady=(15, 0), columnspan=2)
        self.bwlimit_options = ["Sem limite", "1", "5", "10", "25", "50", "100", "200", "500", "1000"]
        self.entrada_bwlimit = ttk.Combobox(main_frame, values=self.bwlimit_options, width=20, state="readonly")
        self.entrada_bwlimit.set("Sem limite")
        self.entrada_bwlimit.grid(row=9, column=0, sticky="w", pady=5)

        tk.Label(main_frame, text="💬 Nome do perfil:", font=("Segoe UI", 10, "bold")).grid(row=10, column=0, sticky="w", pady=(15, 0))
        self.entrada_nome_perfil = tk.Entry(main_frame, width=60)
        self.entrada_nome_perfil.grid(row=11, column=0, sticky="ew", pady=5)
        self.btn_salvar_perfil = tk.Button(main_frame, text="💾 Salvar perfil", command=self.salvar_perfil, relief=tk.RAISED, bd=2)
        self.btn_salvar_perfil.grid(row=11, column=1, sticky="e", padx=(5,0))

        tk.Label(main_frame, text="📂 Selecionar perfil salvo:", font=("Segoe UI", 10, "bold")).grid(row=12, column=0, sticky="w", pady=(10, 0))
        self.combo_perfis = ttk.Combobox(main_frame, values=list(self.perfis.keys()), width=60, state="readonly")
        self.combo_perfis.grid(row=13, column=0, sticky="ew", pady=5)
        
        profile_buttons_frame = tk.Frame(main_frame)
        profile_buttons_frame.grid(row=13, column=1, sticky="e", padx=(5,0))
        self.btn_carregar_perfil = tk.Button(profile_buttons_frame, text="📁 Carregar perfil", command=self.carregar_perfil, relief=tk.RAISED, bd=2)
        self.btn_carregar_perfil.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_deletar_perfil = tk.Button(profile_buttons_frame, text="❌ Deletar perfil", command=self.deletar_perfil, relief=tk.RAISED, bd=2)
        self.btn_deletar_perfil.pack(side=tk.LEFT)

        # Botão para Abrir Log Mais Recente
        self.btn_abrir_log = tk.Button(main_frame, text="📄 Abrir Log Mais Recente", command=self.abrir_log_mais_recente, relief=tk.RAISED, bd=2)
        self.btn_abrir_log.grid(row=14, column=0, columnspan=2, pady=(5, 10)) # Nova linha para o botão de log

        # O único botão de iniciar/parar (linhas seguintes ajustadas)
        self.botao_iniciar = tk.Button(
            main_frame,
            text="🚀 Iniciar Sincronização",
            command=self.toggle_sincronizacao,
            bg="#0078D7", fg="white", font=("Segoe UI", 11, "bold"),
            relief=tk.RAISED, bd=3
        )
        self.botao_iniciar.grid(row=15, column=0, columnspan=2, pady=(20, 10)) # Ajustado o row

        tk.Label(main_frame, textvariable=self.status_var, font=("Segoe UI", 10, "italic")).grid(row=16, column=0, columnspan=2, pady=(10, 5)) # Ajustado o row

        tk.Label(main_frame, textvariable=self.transferido_var, font=("Segoe UI", 9)).grid(row=17, column=0, sticky="w", columnspan=2) # Ajustado o row
        tk.Label(main_frame, textvariable=self.velocidade_var, font=("Segoe UI", 9)).grid(row=18, column=0, sticky="w", columnspan=2) # Ajustado o row
        tk.Label(main_frame, textvariable=self.eta_var, font=("Segoe UI", 9)).grid(row=19, column=0, sticky="w", columnspan=2) # Ajustado o row
        tk.Label(main_frame, textvariable=self.tempo_var, font=("Segoe UI", 9)).grid(row=20, column=0, sticky="w", columnspan=2) # Ajustado o row

        self.progressbar = ttk.Progressbar(main_frame, variable=self.progresso_var, maximum=100, mode='determinate')
        self.progressbar.grid(row=21, column=0, columnspan=2, sticky="ew", pady=(5, 10)) # Ajustado o row

        tk.Label(main_frame, text="Saída do Rclone:", font=("Segoe UI", 10, "bold")).grid(row=22, column=0, sticky="w", pady=(10, 0), columnspan=2) # Ajustado o row
        self.output_text = tk.Text(main_frame, height=10, state="disabled", wrap="word", font=("Consolas", 8))
        self.output_text.grid(row=23, column=0, columnspan=2, sticky="nsew") # Ajustado o row
        self.output_scrollbar = tk.Scrollbar(main_frame, command=self.output_text.yview)
        self.output_scrollbar.grid(row=23, column=2, sticky="ns") # Ajustado o row
        self.output_text.config(yscrollcommand=self.output_scrollbar.set)

        main_frame.rowconfigure(23, weight=1) # Ajustado o row

        tk.Label(main_frame, text="Se o rclone não estiver configurado para o OneDrive, execute:", font=("Segoe UI", 9, "italic")).grid(row=24, column=0, sticky="w", pady=(10, 0), columnspan=2) # Ajustado o row
        tk.Label(main_frame, text="rclone config", font=("Consolas", 9, "bold"), fg="blue").grid(row=25, column=0, columnspan=2) # Ajustado o row
        tk.Label(main_frame, text="no seu terminal.", font=("Segoe UI", 9, "italic")).grid(row=26, column=0, pady=(0, 10), columnspan=2) # Ajustado o row

    def _set_widgets_state(self, state):
        widgets = [
            self.entrada_origem,
            self.combo_onedrive,
            self.btn_escolher_pasta_local,
            self.btn_atualizar_pastas_remotas,
            self.btn_criar_pasta_onedrive,
            self.radio_copy,
            self.radio_sync,
            self.entrada_bwlimit,
            self.entrada_nome_perfil,
            self.btn_salvar_perfil,
            self.combo_perfis,
            self.btn_carregar_perfil,
            self.btn_deletar_perfil,
            self.btn_abrir_log # Adicionado o botão de log aqui
        ]
        for widget in widgets:
            if isinstance(widget, ttk.Combobox):
                widget.config(state='readonly' if state == 'normal' else 'disabled')
            else:
                widget.config(state=state)

    def atualizar_combo_onedrive(self):
        self.combo_onedrive["values"] = listar_pastas_onedrive()

    def escolher_pasta_local(self):
        caminho = filedialog.askdirectory()
        if caminho:
            self.entrada_origem.delete(0, tk.END)
            self.entrada_origem.insert(0, caminho)

    def salvar_perfil(self):
        nome = self.entrada_nome_perfil.get().strip()
        if not nome:
            messagebox.showwarning("Atenção", "Digite um nome para o perfil.")
            return
        self.perfis[nome] = {
            "origem": self.entrada_origem.get(),
            "destino": self.combo_onedrive.get(),
            "modo": self.modo_var.get(),
            "bwlimit": self.entrada_bwlimit.get().strip()
        }
        salvar_json(ARQ_PERFIS, self.perfis)
        self.atualizar_lista_perfis()
        self.entrada_nome_perfil.delete(0, tk.END)
        messagebox.showinfo("Perfil Salvo", f"Perfil '{nome}' salvo com sucesso!")

    def carregar_perfil(self):
        nome = self.combo_perfis.get()
        if nome in self.perfis:
            dados = self.perfis[nome]
            self.entrada_origem.delete(0, tk.END)
            self.entrada_origem.insert(0, dados["origem"])
            self.combo_onedrive.set(dados["destino"])
            self.modo_var.set(dados["modo"])
            bwlimit_val = dados.get("bwlimit", "Sem limite")
            if bwlimit_val not in self.bwlimit_options:
                bwlimit_val = "Sem limite"
            self.entrada_bwlimit.set(bwlimit_val)
            messagebox.showinfo("Perfil Carregado", f"Perfil '{nome}' carregado com sucesso!")
        else:
            messagebox.showwarning("Atenção", "Selecione um perfil para carregar.")

    def atualizar_lista_perfis(self):
        self.combo_perfis["values"] = list(self.perfis.keys())

    def deletar_perfil(self):
        nome = self.combo_perfis.get()
        if nome in self.perfis:
            if messagebox.askyesno("Confirmar", f"Deseja apagar o perfil '{nome}'?"):
                del self.perfis[nome]
                salvar_json(ARQ_PERFIS, self.perfis)
                self.atualizar_lista_perfis()
                self.combo_perfis.set("")
                messagebox.showinfo("Perfil Deletado", f"Perfil '{nome}' deletado com sucesso!")
        else:
            messagebox.showwarning("Atenção", "Selecione um perfil para deletar.")

    def abrir_log_mais_recente(self):
        """
        Encontra e abre o ficheiro de log mais recente.
        """
        # Encontra todos os ficheiros de log com o padrão "log_YYYY-MM-DD_HHhMM.txt"
        lista_de_logs = glob.glob("log_*.txt")
        
        if not lista_de_logs:
            messagebox.showinfo("Log", "Nenhum ficheiro de log encontrado.")
            return

        # Ordena os ficheiros de log por data/hora (o mais recente será o último)
        # O formato do nome do ficheiro permite uma ordenação lexicográfica direta.
        lista_de_logs.sort()
        log_mais_recente = lista_de_logs[-1]

        self.abrir_pasta_log(log_mais_recente)


    def abrir_pasta_log(self, log_file_path):
        """
        Abre a pasta onde o ficheiro de log está localizado.
        """
        log_file_path_abs = os.path.abspath(log_file_path)
        log_directory = os.path.dirname(log_file_path_abs)

        print(f"DEBUG: [abrir_pasta_log] Tentando abrir pasta (caminho absoluto): {log_directory}") # Debug print
        sys.stdout.flush() # Forçar a saída

        if not os.path.exists(log_directory):
            messagebox.showinfo("Log", f"A pasta de log '{log_directory}' não foi encontrada.")
            print(f"DEBUG: [abrir_pasta_log] Pasta de log não encontrada: {log_directory}") # Debug print
            sys.stdout.flush() # Forçar a saída
            return

        try:
            if os.name == 'nt':  # Para Windows
                print(f"DEBUG: [abrir_pasta_log] Usando os.startfile para Windows.") # Debug print
                sys.stdout.flush() # Forçar a saída
                os.startfile(log_directory)
            elif os.name == 'posix':  # Para Linux, macOS
                print(f"DEBUG: [abrir_pasta_log] Tentando xdg-open/open para POSIX.") # Debug print
                sys.stdout.flush() # Forçar a saída
                # Tenta xdg-open para Linux, depois fallback para open para macOS
                try:
                    subprocess.Popen(['xdg-open', log_directory])
                    print(f"DEBUG: [abrir_pasta_log] xdg-open chamado.") # Debug print
                    sys.stdout.flush() # Forçar a saída
                except FileNotFoundError:
                    # Fallback para 'open' para macOS ou outros sistemas baseados em POSIX sem xdg-open
                    subprocess.Popen(['open', log_directory])
                    print(f"DEBUG: [abrir_pasta_log] open chamado (fallback).") # Debug print
                    sys.stdout.flush() # Forçar a saída
                except Exception as e:
                    messagebox.showerror("Erro ao abrir pasta", f"Erro ao tentar abrir a pasta com xdg-open/open: {e}\nVerifique se o comando está disponível no seu PATH.")
                    print(f"DEBUG: [abrir_pasta_log] Erro específico ao abrir pasta (posix): {e}") # Debug print
                    sys.stdout.flush() # Forçar a saída
            else:
                messagebox.showwarning("Abrir Pasta", "Sistema operativo não suportado para abrir pasta automaticamente.")
                print(f"DEBUG: [abrir_pasta_log] SO não suportado para abertura automática: {os.name}") # Debug print
                sys.stdout.flush() # Forçar a saída
            
            # Adicionar um pequeno atraso para permitir que o processo externo inicie
            time.sleep(0.1) # 100 milissegundos
            print(f"DEBUG: [abrir_pasta_log] Atraso de 0.1s concluído.") # Debug print
            sys.stdout.flush() # Forçar a saída

        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir a pasta de log: {e}\nVerifique as permissões ou se o caminho é válido.")
            print(f"DEBUG: [abrir_pasta_log] Erro geral ao abrir pasta: {e}") # Debug print
            sys.stdout.flush() # Forçar a saída


    def criar_nova_pasta_onedrive(self):
        nova_pasta = simpledialog.askstring("Criar Nova Pasta", "Digite o nome da nova pasta no OneDrive:")
        if nova_pasta:
            nova_pasta = nova_pasta.strip()
            valido, caractere = validar_caminho(nova_pasta)
            if not valido:
                messagebox.showerror("Erro de Caractere", f"O nome da pasta contém caractere inválido: '{caractere}'. Por favor, remova-o.")
                return

            self.btn_criar_pasta_onedrive.config(state="disabled")
            self.status_var.set(f"Criando pasta '{nova_pasta}' no OneDrive...")

            def criar_pasta_thread():
                try:
                    comando = ["rclone", "mkdir", f"onedrive:{nova_pasta}"]
                    
                    processo_mkdir = subprocess.run(
                        comando,
                        capture_output=True, text=True, encoding="utf-8", check=False
                    )

                    if processo_mkdir.returncode == 0:
                        self.janela.after(0, lambda: messagebox.showinfo("Sucesso", f"Pasta '{nova_pasta}' criada com sucesso no OneDrive!"))
                        self.janela.after(0, self.atualizar_combo_onedrive)
                        self.janela.after(0, self.combo_onedrive.set, nova_pasta)
                        self.janela.after(0, self.status_var.set, "Pronto")
                    else:
                        erro_msg = processo_mkdir.stderr.strip()
                        self.janela.after(0, lambda: messagebox.showerror("Erro ao Criar Pasta", f"Não foi possível criar a pasta '{nova_pasta}'.\nErro: {erro_msg}"))
                        self.janela.after(0, self.status_var.set, "Erro ao criar pasta")
                except Exception as e:
                    self.janela.after(0, lambda: messagebox.showerror("Erro Inesperado", f"Ocorreu um erro inesperado ao tentar criar a pasta: {e}"))
                    self.janela.after(0, self.status_var.set, "Erro inesperado")
                finally:
                    self.janela.after(0, lambda: self.btn_criar_pasta_onedrive.config(state="normal"))

            threading.Thread(target=criar_pasta_thread, daemon=True).start()

    def toggle_sincronizacao(self):
        """Gerencia o início da sincronização (teste ou real) ou o cancelamento."""
        if not self.sincronizando:
            origem = self.entrada_origem.get().replace("\\", "/")
            destino_pasta = self.combo_onedrive.get().strip()

            valido, caractere = validar_caminho(origem)
            if not valido:
                messagebox.showerror("Erro", f"Caminho da pasta local contém caractere inválido: '{caractere}'. Por favor, remova-o.")
                self._reset_ui_buttons()
                return

            if not origem or not destino_pasta:
                messagebox.showerror("Erro", "Preencha todos os campos obrigatórios (Pasta local e Pasta remota).")
                self._reset_ui_buttons()
                return

            if not os.path.exists(origem):
                messagebox.showerror("Erro", f"A pasta local '{origem}' não existe. Por favor, verifique o caminho.")
                self._reset_ui_buttons()
                return

            if destino_pasta and destino_pasta not in listar_pastas_onedrive():
                messagebox.showwarning("Pasta Remota Inexistente", f"A pasta remota '{destino_pasta}' não existe no OneDrive. Por favor, crie-a usando o botão 'Criar nova pasta no OneDrive' ou selecione uma pasta existente.")
                self._reset_ui_buttons()
                return

            # Passo 01: Opção de teste
            resposta_teste = messagebox.askyesno(
                "Iniciar Sincronização",
                "Deseja fazer um teste (dry-run)?\n\nSe sim, o teste será executado. Se não, a sincronização real será iniciada."
            )
            
            self.sincronizando = True
            self._set_sync_active_button_state()
            self.executar_sincronizacao(is_dry_run=resposta_teste)
        else:
            self._handle_cancel_sync()

    def _set_sync_active_button_state(self):
        self.botao_iniciar.config(
            text="❌ Parar Sincronização",
            bg="red",
            command=self._handle_cancel_sync
        )

    def _set_sync_inactive_button_state(self):
        self.botao_iniciar.config(
            text="🚀 Iniciar Sincronização",
            bg="#0078D7",
            command=self.toggle_sincronizacao
        )

    def _handle_cancel_sync(self):
        if self.processo and self.processo.poll() is None:
            confirmar = messagebox.askyesno(
                "Cancelar sincronização",
                "Deseja realmente cancelar a sincronização em andamento? Arquivos parciais podem ficar no destino."
            )
            if confirmar:
                self.processo.terminate()
                self.status_var.set("⚠️ Sincronização cancelada pelo usuário")
                self.resetar_infos()
                self._reset_ui_buttons()
        else:
            self.resetar_infos()
            self._reset_ui_buttons()

    def _reset_ui_buttons(self):
        self.sincronizando = False
        self._set_sync_inactive_button_state()
        self._set_widgets_state('normal')

    def executar_sincronizacao(self, is_dry_run):
        origem = self.entrada_origem.get().replace("\\", "/")
        destino_pasta = self.combo_onedrive.get().strip()
        destino = f"onedrive:{destino_pasta}"
        modo = self.modo_var.get()
        bwlimit_str = self.entrada_bwlimit.get().strip()

        # Passo 02: Se deseja sincronizar (somente para sincronização real)
        if not is_dry_run:
            confirmar_real_sync = messagebox.askyesno("Confirmação de Sincronização", f"Modo de operação: {modo.upper()}\n\nDeseja realmente iniciar a sincronização real?")
            if not confirmar_real_sync:
                self._reset_ui_buttons() # Volta para a configuração
                return
        
        self.janela.after(0, lambda: self._set_widgets_state('disabled'))

        def processo_thread():
            self.janela.after(0, self.output_text.config, {"state": "normal"})
            self.janela.after(0, self.output_text.delete, "1.0", tk.END)
            self.status_var.set(f"🚀 Sincronizando ({'Teste' if is_dry_run else 'Real'})...")
            log_nome = datetime.now().strftime("log_%Y-%m-%d_%Hh%M.txt")
            inicio = time.time()

            with open(log_nome, "w", encoding="utf-8") as log:
                comando = ["rclone", modo, origem, destino, "--stats-one-line", "--stats", "1s", "--verbose"]
                if is_dry_run:
                    comando.append("--dry-run")
                
                if bwlimit_str != "Sem limite":
                    try:
                        mbps = float(bwlimit_str)
                        mb_per_sec = mbps * 0.125
                        comando.append(f"--bwlimit={mb_per_sec}M")
                    except ValueError:
                        self.janela.after(0, lambda: messagebox.showerror("Erro de Banda", "O limite de banda selecionado não é válido."))
                        self.janela.after(0, self._reset_ui_buttons)
                        return

                self.processo = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1) 

                stdout_lines_read = 0
                stderr_lines_read = 0

                def read_stdout():
                    nonlocal stdout_lines_read
                    for linha in iter(self.processo.stdout.readline, ''):
                        stdout_lines_read += 1
                        log.write(linha)
                        self.janela.after(0, self.output_text.insert, tk.END, f"[Rclone] {linha}")
                        self.janela.after(0, self.output_text.see, tk.END)
                        
                    self.processo.stdout.close()

                def read_stderr():
                    nonlocal stderr_lines_read
                    for linha in iter(self.processo.stderr.readline, ''):
                        stderr_lines_read += 1
                        log.write(f"[STDERR] {linha}")
                        self.janela.after(0, self.output_text.insert, tk.END, f"[Rclone Erro/Aviso/Progresso] {linha}")

                        transferido, total, porcentagem, velocidade, eta = extrair_stats_completos(linha)
                        if transferido is not None:
                            self.janela.after(0, self.transferido_var.set, f"Transferido: {transferido} MiB / {total} MiB")
                            self.janela.after(0, self.velocidade_var.set, f"Velocidade: {velocidade}")
                            self.janela.after(0, self.eta_var.set, f"ETA: {eta}")
                            # Calcular e atualizar o tempo decorrido
                            current_time = time.time()
                            elapsed_duration = current_time - inicio
                            elapsed_formatted = f"{int(elapsed_duration // 60)}m {int(elapsed_duration % 60)}s"
                            self.janela.after(0, self.tempo_var.set, f"Tempo decorrido: {elapsed_formatted}")
                            self.janela.after(0, self.progresso_var.set, float(porcentagem))
                        
                        self.janela.after(0, self.output_text.see, tk.END)
                    self.processo.stderr.close()

                stdout_thread = threading.Thread(target=read_stdout, daemon=True)
                stderr_thread = threading.Thread(target=read_stderr, daemon=True)

                stdout_thread.start()
                stderr_thread.start()

                self.processo.wait()

                stdout_thread.join()
                stderr_thread.join()

                fim = time.time()
                duracao = fim - inicio
                tempo_formatado = f"{int(duracao // 60)}m {int(duracao % 60)}s"

                if self.processo.returncode != 0:
                    final_stderr_output_fallback = self.processo.stderr.read() 
                    if final_stderr_output_fallback:
                        log.write("\n--- ERRO FINAL (fallback) ---\n")
                        log.write(final_stderr_output_fallback)
                        self.janela.after(0, self.output_text.insert, tk.END, f"\n[ERRO FINAL Rclone] {final_stderr_output_fallback}")
                        self.janela.after(0, self.output_text.see, tk.END)

                    self.janela.after(0, self.status_var.set, "❌ Sincronização falhou")
                    self.janela.after(0, lambda: messagebox.showerror(
                        "Erro na Sincronização",
                        f"A sincronização falhou. Verifique o log ({log_nome}) para mais detalhes e a saída do Rclone na interface."
                    ))
                    self.janela.after(0, self.resetar_infos)
                    self.janela.after(0, self._reset_ui_buttons)
                else:
                    self.janela.after(0, self.status_var.set, f"✅ Sincronização concluída em {tempo_formatado}")
                    final_transfer_info = self.transferido_var.get() # Captura a informação final de transferência
                    # Apenas pergunta sobre o log se for uma sincronização REAL (não dry-run)
                    if not is_dry_run:
                        # Passo 03: Finalizou a sincronização, aparece a opção de ver o log
                        self.janela.after(0, lambda: self._ask_open_log_after_sync(tempo_formatado, final_transfer_info))
                    else:
                        # Se for dry-run, pergunta se deseja iniciar a sincronização real
                        self.janela.after(0, lambda: self._ask_real_sync_after_test(tempo_formatado))


                self.janela.after(0, self.output_text.config, {"state": "disabled"})

            if self.processo and self.processo.poll() is None:
                self.processo.terminate()
            
        threading.Thread(target=processo_thread, daemon=True).start()

    def _ask_real_sync_after_test(self, tempo_formatado):
        """
        Após um teste bem-sucedido, pergunta ao usuário se deseja iniciar a sincronização real.
        Se não, reseta o estado da aplicação.
        """
        # Passo 02: Se deseja sincronizar (após dry-run)
        resposta = messagebox.askquestion(
            "Teste Concluído",
            f"✅ Teste concluído com sucesso em {tempo_formatado}.\n\nDeseja iniciar a sincronização real agora?"
        )
        if resposta == "yes":
            self.sincronizando = True
            self._set_sync_active_button_state()
            self.janela.after(0, lambda: self._set_widgets_state('disabled'))
            self.executar_sincronizacao(is_dry_run=False)
        else:
            # Se não deseja sincronizar, reseta o app
            self.janela.after(0, self.reset_app_state)

    def _ask_open_log_after_sync(self, tempo_formatado, final_transfer_info):
        """
        Após a sincronização real, exibe uma mensagem de conclusão com informações e reseta a aplicação.
        """
        messagebox.showinfo(
            "Sincronização Concluída",
            f"✅ Sincronização concluída em {tempo_formatado}.\n\n{final_transfer_info}"
        )
        # A aplicação é resetada após o usuário clicar em OK.
        self.reset_app_state()

    def reset_app_state(self):
        """Reseta todos os campos da interface para o estado inicial."""
        self.entrada_origem.delete(0, tk.END)
        self.combo_onedrive.set("")
        self.modo_var.set("copy")
        self.entrada_bwlimit.set("Sem limite")
        self.entrada_nome_perfil.delete(0, tk.END)
        self.combo_perfis.set("")
        self.atualizar_lista_perfis()

        self.resetar_infos()
        self._reset_ui_buttons()
        self.status_var.set("Pronto")

    def resetar_infos(self):
        """Reseta as informações de status na GUI."""
        self.velocidade_var.set("Velocidade: -")
        self.tempo_var.set("Tempo decorrido: 0m 0s")
        self.eta_var.set("ETA: -")
        self.transferido_var.set("Transferido: - / - MiB")
        self.progresso_var.set(0)
        self.output_text.config(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state="disabled")

CloudEaseApp()
