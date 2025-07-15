# CloudEase

CloudEase é uma aplicação gráfica para Windows que facilita o backup e sincronização de pastas locais com o OneDrive usando o rclone.

## Funcionalidades principais
- Interface intuitiva em português
- Sincronização e cópia de pastas locais para o OneDrive
- Teste de sincronização (dry-run) antes de executar de verdade
- Limite de banda configurável
- Perfis salvos para diferentes rotinas de backup
- Criação de pastas remotas no OneDrive
- Visualização de logs e progresso detalhado

## Pré-requisitos
- [rclone](https://rclone.org/downloads/) instalado e configurado para o OneDrive
- Python 3.x instalado

## Como usar
1. Execute o arquivo `CloudEase.py`.
2. Escolha a pasta local e a pasta remota no OneDrive.
3. Se desejar, configure o limite de banda e salve perfis para uso futuro.
4. Clique em "Iniciar Sincronização" e siga as instruções na tela.
5. Consulte os logs para detalhes das operações.

## Observações
- O rclone deve estar configurado com um remote chamado `onedrive`.
- Os logs são salvos automaticamente na pasta do programa.

---
Desenvolvido por Jailton Gonçalves.