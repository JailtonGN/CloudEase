import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import subprocess
import os
import json
from datetime import datetime, timedelta
import re
import threading
import time

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
        messagebox.showerror("Erro ao listar OneDrive", f"Não foi possível listar pastas do OneDrive. Verifique sua conexão ou configuração do rclone.\nErro: {e}")
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
    Exemplo de linha do rclone (stats one line):
    Transferred:    10.345 MiB / 50.000 MiB, 20%, 1.234 MiB/s, ETA 00:40
    """
    padrao = (
        r"Transferred:\s+([\d\.]+) MiB / ([\d\.]+) MiB, ([\d]+)%,.*?,\s*([\d\.]+) MiB/s, ETA (\d+:\d+)"
    )
    match = re.search(padrao, linha)
    if match:
        transferido = match.group(1)
        total = match.group(2)
        porcentagem = match.group(3)
        velocidade = match.group(4)
        eta = match.group(5)
        return transferido, total, porcentagem, velocidade, eta
    return None, None, None, None, None

def validar_caminho(path):
    """
    Valida caracteres básicos em um caminho.
    Nota: Esta validação é básica e visa caracteres de controle ASCII.
    Sistemas de arquivos modernos podem ter outras restrições.
    """
    for c in path:
        if ord(c) < 32 or ord(c) == 127: # Caracteres de controle ASCII
            return False, c
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
                # Extrai a data do nome do arquivo (ex: log_2023-01-01_10h30.txt)
                data_str = filename[4:14] # "YYYY-MM-DD"
                log_date = datetime.strptime(data_str, "%Y-%m-%d")
                if (hoje - log_date).days > dias_manter:
                    os.remove(filename)
                    print(f"Log antigo removido: {filename}")
            except (ValueError, IndexError):
                # Ignora arquivos que não correspondem ao padrão de data esperado
                continue
            except OSError as e:
                print(f"Erro ao remover log {filename}: {e}")


class CloudEaseApp:
    def __init__(self):
        self.processo = None
        self.sincronizando = False
        self.perfis = carregar_json(ARQ_PERFIS)

        # Limpa logs antigos ao iniciar a aplicação
        limpar_logs_antigos(DIAS_MANTER_LOGS)

        self.janela = tk.Tk()
        self.janela.title("CloudEase")
        # Ajusta o tamanho inicial para acomodar todos os elementos e permite redimensionamento
        self.janela.geometry("580x680") 
        self.janela.resizable(True, True) # Permite redimensionamento horizontal e vertical

        self.status_var = tk.StringVar(value="Pronto")
        self.modo_var = tk.StringVar(value="copy")

        # Variáveis para infos detalhadas (mantidas para compatibilidade, mas não exibidas)
        self.velocidade_var = tk.StringVar(value="Velocidade: -")
        self.tempo_var = tk.StringVar(value="Tempo decorrido: 0m 0s")
        self.eta_var = tk.StringVar(value="ETA: -")
        self.transferido_var = tk.StringVar(value="Transferido: - / - MiB")
        # self.progresso_var = tk.DoubleVar(value=0) # Variável para a barra de progresso - REMOVIDA

        self.setup_ui()

        if not verificar_rclone():
            messagebox.showerror("Erro", "⚠️ Rclone não está instalado ou não foi encontrado no sistema. Por favor, instale-o e configure-o para o OneDrive.")

        self.janela.mainloop()

    def setup_ui(self):
        # Frame principal para melhor organização
        main_frame = tk.Frame(self.janela, padx=10, pady=10)
        # Usa pack com expand=True e fill=BOTH para que o frame principal se expanda com a janela
        main_frame.pack(fill=tk.BOTH, expand=True) 

        tk.Label(main_frame, text="📁 Pasta local:", font=("Segoe UI", 10, "bold")).pack(pady=(10, 0), anchor="w")
        self.entrada_origem = tk.Entry(main_frame, width=70)
        self.entrada_origem.pack(pady=5, fill=tk.X)
        self.btn_escolher_pasta_local = tk.Button(main_frame, text="Escolher pasta", command=self.escolher_pasta_local, relief=tk.RAISED, bd=2)
        self.btn_escolher_pasta_local.pack(pady=2) # Removido anchor="w" para centralizar

        tk.Label(main_frame, text="☁️ Pasta remota no OneDrive:", font=("Segoe UI", 10, "bold")).pack(pady=(15, 0), anchor="w")
        self.combo_onedrive = ttk.Combobox(main_frame, values=listar_pastas_onedrive(), width=60)
        self.combo_onedrive.pack(fill=tk.X)
        self.btn_atualizar_pastas_remotas = tk.Button(main_frame, text="🔄 Atualizar pastas remotas", command=self.atualizar_combo_onedrive, relief=tk.RAISED, bd=2)
        self.btn_atualizar_pastas_remotas.pack(pady=2) # Removido anchor="w" para centralizar

        tk.Label(main_frame, text="🔄 Modo de operação:", font=("Segoe UI", 10, "bold")).pack(pady=(15, 0), anchor="w")
        self.radio_copy = tk.Radiobutton(main_frame, text="Copiar (seguro)", variable=self.modo_var, value="copy", font=("Segoe UI", 9))
        self.radio_copy.pack(anchor="w")
        self.radio_sync = tk.Radiobutton(main_frame, text="Sincronizar (espelha e apaga)", variable=self.modo_var, value="sync", font=("Segoe UI", 9))
        self.radio_sync.pack(anchor="w")

        tk.Label(main_frame, text="📶 Limite de banda upload (Mbps):", font=("Segoe UI", 10, "bold")).pack(pady=(15, 0), anchor="w")
        
        # Substituído Entry por Combobox para limite de banda
        self.bwlimit_options = ["Sem limite", "1", "5", "10", "25", "50", "100", "200", "500", "1000"] # Opções em Mbps
        self.entrada_bwlimit = ttk.Combobox(main_frame, values=self.bwlimit_options, width=20, state="readonly")
        self.entrada_bwlimit.set("Sem limite") # Valor padrão
        self.entrada_bwlimit.pack(pady=5) # Removido fill=tk.X para centralizar, ajustado pady

        tk.Label(main_frame, text="💬 Nome do perfil:", font=("Segoe UI", 10, "bold")).pack(pady=(15, 0), anchor="w")
        self.entrada_nome_perfil = tk.Entry(main_frame, width=60)
        self.entrada_nome_perfil.pack(pady=5, fill=tk.X)
        self.btn_salvar_perfil = tk.Button(main_frame, text="💾 Salvar perfil", command=self.salvar_perfil, relief=tk.RAISED, bd=2)
        self.btn_salvar_perfil.pack(pady=2) # Removido anchor="w" para centralizar

        tk.Label(main_frame, text="📂 Selecionar perfil salvo:", font=("Segoe UI", 10, "bold")).pack(pady=(10, 0), anchor="w")
        self.combo_perfis = ttk.Combobox(main_frame, values=list(self.perfis.keys()), width=60, state="readonly")
        self.combo_perfis.pack(fill=tk.X)
        
        # Frame para os botões de perfil
        profile_buttons_frame = tk.Frame(main_frame)
        profile_buttons_frame.pack(pady=5) # Removido anchor="w" para centralizar
        self.btn_carregar_perfil = tk.Button(profile_buttons_frame, text="📁 Carregar perfil", command=self.carregar_perfil, relief=tk.RAISED, bd=2)
        self.btn_carregar_perfil.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_deletar_perfil = tk.Button(profile_buttons_frame, text="❌ Deletar perfil", command=self.deletar_perfil, relief=tk.RAISED, bd=2)
        self.btn_deletar_perfil.pack(side=tk.LEFT)

        # O único botão de iniciar/parar
        self.botao_iniciar = tk.Button(
            main_frame,
            text="🚀 Iniciar Sincronização",
            command=self.toggle_sincronizacao, # Chamará a lógica de teste/real ou cancelamento
            bg="#0078D7", fg="white", font=("Segoe UI", 11, "bold"),
            relief=tk.RAISED, bd=3
        )
        self.botao_iniciar.pack(pady=(20, 10))

        # Status principal
        tk.Label(main_frame, textvariable=self.status_var, font=("Segoe UI", 10, "italic")).pack(pady=(10, 5))

        # Dica de configuração do rclone
        tk.Label(main_frame, text="Se o rclone não estiver configurado para o OneDrive, execute:", font=("Segoe UI", 9, "italic")).pack(pady=(10, 0), anchor="w")
        tk.Label(main_frame, text="rclone config", font=("Consolas", 9, "bold"), fg="blue").pack() # Removido anchor="w" para centralizar
        tk.Label(main_frame, text="no seu terminal.", font=("Segoe UI", 9, "italic")).pack(pady=(0, 10)) # Removido anchor="w" para centralizar

    def _set_widgets_state(self, state):
        """Define o estado (normal/disabled) de todos os widgets de entrada e botões, exceto o botão principal."""
        widgets = [
            self.entrada_origem,
            self.combo_onedrive,
            self.btn_escolher_pasta_local,
            self.btn_atualizar_pastas_remotas,
            self.radio_copy,
            self.radio_sync,
            self.entrada_bwlimit, # Incluído o novo combobox
            self.entrada_nome_perfil,
            self.btn_salvar_perfil,
            self.combo_perfis,
            self.btn_carregar_perfil,
            self.btn_deletar_perfil
        ]
        for widget in widgets:
            # Comboboxes precisam de tratamento especial para 'state'
            if isinstance(widget, ttk.Combobox):
                widget.config(state='readonly' if state == 'normal' else 'disabled')
            else:
                widget.config(state=state)

    def atualizar_combo_onedrive(self):
        """Atualiza a lista de pastas do OneDrive no combobox."""
        self.combo_onedrive["values"] = listar_pastas_onedrive()

    def escolher_pasta_local(self):
        """Abre uma caixa de diálogo para o usuário escolher a pasta local."""
        caminho = filedialog.askdirectory()
        if caminho:
            self.entrada_origem.delete(0, tk.END)
            self.entrada_origem.insert(0, caminho)

    def salvar_perfil(self):
        """Salva as configurações atuais como um novo perfil."""
        nome = self.entrada_nome_perfil.get().strip()
        if not nome:
            messagebox.showwarning("Atenção", "Digite um nome para o perfil.")
            return
        self.perfis[nome] = {
            "origem": self.entrada_origem.get(),
            "destino": self.combo_onedrive.get(),
            "modo": self.modo_var.get(),
            "bwlimit": self.entrada_bwlimit.get().strip() # Pega o valor do combobox
        }
        salvar_json(ARQ_PERFIS, self.perfis)
        self.atualizar_lista_perfis()
        self.entrada_nome_perfil.delete(0, tk.END)
        messagebox.showinfo("Perfil Salvo", f"Perfil '{nome}' salvo com sucesso!")


    def carregar_perfil(self):
        """Carrega um perfil salvo e preenche os campos da GUI."""
        nome = self.combo_perfis.get()
        if nome in self.perfis:
            dados = self.perfis[nome]
            self.entrada_origem.delete(0, tk.END)
            self.entrada_origem.insert(0, dados["origem"])
            self.combo_onedrive.set(dados["destino"])
            self.modo_var.set(dados["modo"])
            # Define o valor do combobox de limite de banda
            bwlimit_val = dados.get("bwlimit", "Sem limite")
            if bwlimit_val not in self.bwlimit_options: # Garante que o valor carregado é uma opção válida
                bwlimit_val = "Sem limite"
            self.entrada_bwlimit.set(bwlimit_val)
            messagebox.showinfo("Perfil Carregado", f"Perfil '{nome}' carregado com sucesso!")
        else:
            messagebox.showwarning("Atenção", "Selecione um perfil para carregar.")

    def atualizar_lista_perfis(self):
        """Atualiza o combobox de perfis com os perfis salvos."""
        self.combo_perfis["values"] = list(self.perfis.keys())

    def deletar_perfil(self):
        """Deleta um perfil salvo."""
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

    def toggle_sincronizacao(self):
        """Gerencia o início da sincronização (teste ou real) ou o cancelamento."""
        if not self.sincronizando:
            # Pergunta se deseja fazer um teste antes
            resposta_teste = messagebox.askyesno(
                "Iniciar Sincronização",
                "Deseja fazer um teste (dry-run) antes de iniciar a sincronização real?"
            )
            if resposta_teste:
                self.sincronizando = True
                self._set_sync_active_button_state()
                # A desabilitação dos widgets é movida para executar_sincronizacao,
                # após as validações e confirmações iniciais.
                self.executar_sincronizacao(is_dry_run=True)
            else:
                self.sincronizando = True
                self._set_sync_active_button_state()
                # A desabilitação dos widgets é movida para executar_sincronizacao,
                # após as validações e confirmações iniciais.
                self.executar_sincronizacao(is_dry_run=False)
        else:
            self._handle_cancel_sync()

    def _set_sync_active_button_state(self):
        """Configura o botão para o estado 'Parar Sincronização'."""
        self.botao_iniciar.config(
            text="❌ Parar Sincronização",
            bg="red",
            command=self._handle_cancel_sync # Altera o comando do botão para cancelar
        )

    def _set_sync_inactive_button_state(self):
        """Configura o botão para o estado 'Iniciar Sincronização'."""
        self.botao_iniciar.config(
            text="🚀 Iniciar Sincronização",
            bg="#0078D7",
            command=self.toggle_sincronizacao # Altera o comando do botão para iniciar
        )

    def _handle_cancel_sync(self):
        """Lida com o cancelamento da sincronização."""
        if self.processo and self.processo.poll() is None: # Verifica se o processo ainda está rodando
            confirmar = messagebox.askyesno(
                "Cancelar sincronização",
                "Deseja realmente cancelar a sincronização em andamento? Arquivos parciais podem ficar no destino."
            )
            if confirmar:
                self.processo.terminate()
                self.status_var.set("⚠️ Sincronização cancelada pelo usuário")
                self.resetar_infos()
                self._reset_ui_buttons() # Reseta os botões da UI e reabilita widgets
        else: # Processo já terminou, mas o botão ainda está em "Parar"
            self.resetar_infos() # Limpa as informações de status
            self._reset_ui_buttons() # Reseta os botões da UI e reabilita widgets


    def _reset_ui_buttons(self):
        """Reseta a visibilidade e o estado do botão principal, e reabilita outros widgets."""
        self.sincronizando = False
        self._set_sync_inactive_button_state()
        self._set_widgets_state('normal') # Reabilita todos os outros widgets

    def executar_sincronizacao(self, is_dry_run):
        """Prepara e executa o comando rclone em uma thread separada."""
        origem = self.entrada_origem.get().replace("\\", "/") # Normaliza para barras frontais
        destino_pasta = self.combo_onedrive.get().strip()
        destino = f"onedrive:{destino_pasta}"
        modo = self.modo_var.get()
        bwlimit_str = self.entrada_bwlimit.get().strip()

        # Validação de caminho
        valido, caractere = validar_caminho(origem)
        if not valido:
            messagebox.showerror("Erro", f"Caminho da pasta local contém caractere inválido: '{caractere}'. Por favor, remova-o.")
            self._reset_ui_buttons()
            return

        # Validação de campos obrigatórios
        if not origem or not destino_pasta:
            messagebox.showerror("Erro", "Preencha todos os campos obrigatórios (Pasta local e Pasta remota).")
            self._reset_ui_buttons()
            return

        # Validação de existência da pasta local
        if not os.path.exists(origem):
            messagebox.showerror("Erro", f"A pasta local '{origem}' não existe. Por favor, verifique o caminho.")
            self._reset_ui_buttons()
            return

        # Validação da pasta remota (apenas se não estiver vazia)
        if destino_pasta and destino_pasta not in listar_pastas_onedrive():
            if not messagebox.askyesno("Pasta Remota Inexistente", f"A pasta remota '{destino_pasta}' não existe no OneDrive. Deseja criá-la e continuar a sincronização?"):
                self._reset_ui_buttons()
                return

        # Confirmação do modo de operação (apenas para a sincronização real, o teste já tem sua confirmação)
        if not is_dry_run:
            confirmar = messagebox.askyesno("Confirmação", f"Modo de operação: {modo.upper()}\n\nDeseja continuar?")
            if not confirmar:
                self._reset_ui_buttons() # Reseta UI se o usuário cancelar a confirmação
                return
        
        # SOMENTE AQUI, DEPOIS DE TODAS AS VALIDAÇÕES E CONFIRMAÇÕES, DESABILITE OS WIDGETS
        self.janela.after(0, lambda: self._set_widgets_state('disabled'))


        def processo_thread():
            """Função executada em uma thread separada para o processo rclone."""
            self.status_var.set(f"🚀 Sincronizando ({'Teste' if is_dry_run else 'Real'})...")
            log_nome = datetime.now().strftime("log_%Y-%m-%d_%Hh%M.txt")
            inicio = time.time()

            with open(log_nome, "w", encoding="utf-8") as log:
                comando = ["rclone", modo, origem, destino, "--stats-one-line", "--stats", "1s"]
                if is_dry_run: # Usa o parâmetro passado diretamente
                    comando.append("--dry-run")
                
                # Lógica para o limite de banda do combobox
                if bwlimit_str != "Sem limite":
                    try:
                        mbps = float(bwlimit_str)
                        mb_per_sec = mbps * 0.125 # Convertendo Mbps para MiB/s (1 byte = 8 bits, 1 MiB = 1.048.576 bytes)
                        comando.append(f"--bwlimit={mb_per_sec}M")
                    except ValueError:
                        self.janela.after(0, lambda: messagebox.showerror("Erro de Banda", "O limite de banda selecionado não é válido."))
                        self.janela.after(0, self._reset_ui_buttons)
                        return # Sai da thread se o valor for inválido

                # Captura stdout e stderr separadamente para melhor tratamento de erros
                self.processo = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")

                # Thread para ler stdout
                def read_stdout():
                    for linha in iter(self.processo.stdout.readline, ''):
                        log.write(linha)
                        # As variáveis de velocidade, tempo, eta e transferido ainda são atualizadas
                        # para fins de log ou depuração, embora não exibidas na UI.
                        # Não há mais barra de progresso para atualizar.
                    self.processo.stdout.close()

                # Inicia a thread para ler stdout
                stdout_thread = threading.Thread(target=read_stdout, daemon=True)
                stdout_thread.start()

                # Espera o processo rclone terminar
                self.processo.wait()
                stdout_thread.join() # Garante que toda a saída stdout foi lida

                fim = time.time()
                duracao = fim - inicio
                tempo_formatado = f"{int(duracao // 60)}m {int(duracao % 60)}s"

                if self.processo.returncode != 0:
                    stderr_output = self.processo.stderr.read() # Lê a saída de erro
                    log.write("\n--- ERRO ---\n")
                    log.write(stderr_output)
                    self.janela.after(0, self.status_var.set, "❌ Sincronização falhou")
                    self.janela.after(0, lambda: messagebox.showerror(
                        "Erro na Sincronização",
                        f"A sincronização falhou. Verifique o log para mais detalhes.\n\nDetalhes do erro:\n{stderr_output[:500]}..." # Limita a exibição do erro
                    ))
                    self.janela.after(0, self.resetar_infos)
                    self.janela.after(0, self._reset_ui_buttons)
                else:
                    self.janela.after(0, self.status_var.set, f"✅ Sincronização concluída em {tempo_formatado}")
                    if is_dry_run:
                        # Após um teste bem-sucedido, pergunta se deseja iniciar a sincronização real
                        self.janela.after(0, lambda: self._ask_real_sync_after_test(tempo_formatado))
                    else:
                        # Após a sincronização real, pergunta se deseja fazer outra
                        self.janela.after(0, lambda: self._ask_another_sync(tempo_formatado))

                self.janela.after(0, self.resetar_infos)
                self.janela.after(0, self._reset_ui_buttons)
                self.processo.stderr.close() # Fecha o stderr

            # Garante que o processo foi encerrado e seus recursos liberados
            if self.processo and self.processo.poll() is None:
                self.processo.terminate()
            
        # Inicia a thread principal do processo
        threading.Thread(target=processo_thread, daemon=True).start()

    def _ask_real_sync_after_test(self, tempo_formatado):
        """Pergunta ao usuário se deseja iniciar a sincronização real após um teste bem-sucedido."""
        resposta = messagebox.askquestion(
            "Teste Concluído",
            f"✅ Teste concluído com sucesso em {tempo_formatado}.\n\nDeseja iniciar a sincronização real agora?"
        )
        if resposta == "yes":
            self.sincronizando = True # Re-seta para iniciar a sincronização real
            self._set_sync_active_button_state()
            self.janela.after(0, lambda: self._set_widgets_state('disabled')) # Desabilita os outros widgets
            self.executar_sincronizacao(is_dry_run=False)
        else:
            self.janela.after(0, self.reset_app_state) # Reseta o app se não quiser a sync real

    def _ask_another_sync(self, tempo_formatado):
        """Pergunta ao usuário se deseja fazer outra sincronização e reseta o app se sim, ou fecha se não."""
        resposta = messagebox.askquestion(
            "Finalizado",
            f"✅ Sincronização concluída em {tempo_formatado}\n\nDeseja fazer outra sincronização?"
        )
        if resposta == "yes":
            self.janela.after(0, self.reset_app_state) # Reseta o app
        else:
            self.janela.destroy()

    def reset_app_state(self):
        """Reseta todos os campos da interface para o estado inicial."""
        self.entrada_origem.delete(0, tk.END)
        self.combo_onedrive.set("")
        self.modo_var.set("copy")
        self.entrada_bwlimit.set("Sem limite") # Reseta o combobox de banda
        self.entrada_nome_perfil.delete(0, tk.END)
        self.combo_perfis.set("") # Limpa a seleção do combobox de perfis
        self.atualizar_lista_perfis() # Garante que a lista de perfis esteja atualizada

        self.resetar_infos() # Reseta as informações de status
        self._reset_ui_buttons() # Reseta os botões de iniciar/cancelar e reabilita widgets
        self.status_var.set("Pronto") # Reseta o status principal

    def resetar_infos(self):
        """Reseta as informações de status na GUI."""
        # Mantém as variáveis, mas elas não são mais exibidas diretamente
        self.velocidade_var.set("Velocidade: -")
        self.tempo_var.set("Tempo decorrido: 0m 0s")
        self.eta_var.set("ETA: -")
        self.transferido_var.set("Transferido: - / - MiB")
        # self.progresso_var.set(0) # Variável para a barra de progresso - REMOVIDA

CloudEaseApp()
