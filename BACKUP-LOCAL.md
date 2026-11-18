# Backup local do Conselho do dia

Use este procedimento quando o GitHub Actions falhar. O script exige a branch `main`, o servidor serif-sh já respondendo em `http://127.0.0.1:5173/` e o clone em `/home/box/repos/serif-sh` no commit `abc59e082e476385326f7a7e840f08965f9e6f00`. Ele não inicia nem encerra servidores. Requer o ambiente `/workspace/conselho-venv`, as dependências de renderização e o 1Password CLI autenticado com acesso ao item do cofre Bots.

Para verificar os pré-requisitos sem alterar o repositório ou publicar:

```bash
/workspace/conselho-venv/bin/python /workspace/conselho-do-dia-x/scripts/backup_local.py --check
```

Para executar o backup:

```bash
/workspace/conselho-venv/bin/python /workspace/conselho-do-dia-x/scripts/backup_local.py
```

O script atualiza `main` com `git pull --ff-only`, verifica o estado e a pendência, obtém as credenciais em memória, executa o dry-run e prepara a tentativa. A persistência usa `ci_state.py`, que faz commit e push do estado antes e depois da publicação. A publicação é chamada no máximo uma vez; o resultado é persistido mesmo se ela falhar. A saída final é o link ou o motivo da falha.

Se houver pendência ou falha na publicação ou na persistência, não repita a tentativa: confira o X e siga a recuperação no `README.md`. O modo `--check` não faz pull, dry-run ou consulta de posts no X; confira também se o cartão do dia já foi publicado antes de executar o backup. Nunca coloque credenciais em arquivos.
