# Conselho do dia no X

Automação para transformar os conselhos de H. Jackson Brown, Jr., do *Pequeno Manual de Instruções para a Vida*, em cartões PNG do serif.sh e posts no X. O modo padrão é dry-run; publicar exige `--publish`.

## Arquivos

- `daily.py`: coordena renderização, postagem, estado e registro diário.
- `render.py`: gera `out/conselho-<n>.png` e verifica overflow e OCR.
- `post.py`: valida o post e usa OAuth 1.0a para acessar o X.
- `conselhos.json`: lista de 1001 objetos com `n` e `text`.
- `estado.example.json`: modelo do estado; `estado.json` guarda `proximo`, `ultimo_enviado` e `data_ultimo_envio`.
- `.env.example`: modelo das credenciais; `.env` contém os valores locais.
- `log.jsonl`: registro de publicações confirmadas (`n`, `id`, `url`, `data`).
- [README-render.md](README-render.md) e [README-post.md](README-post.md): detalhes dos scripts individuais.

## Requisitos e instalação

Python 3.10+, Node.js com npm, Tesseract com português e Chromium do Playwright.

Clone e inicie o serif.sh em outro terminal:

```bash
git clone https://github.com/prof-ramos/serif-sh
cd serif-sh
npm install && npm run dev -- --port 5173 --host 127.0.0.1
```

Instale o OCR no Debian/Ubuntu:

```bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-por
```

No macOS, os pacotes equivalentes via Homebrew são:

```bash
brew install tesseract tesseract-lang
```

No diretório deste projeto, de preferência em um ambiente virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install playwright Pillow
python -m playwright install chromium
```

## Configuração do X e estado

Crie um app no X Developer Portal com permissão **Read and Write** e gere as credenciais OAuth 1.0a de usuário com essa permissão. Configure:

```bash
cp .env.example .env
chmod 600 .env
cp estado.example.json estado.json
```

Preencha `.env` com `X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_ACCESS_TOKEN` e `X_ACCESS_TOKEN_SECRET`. Variáveis do ambiente têm prioridade. O arquivo padrão fica ao lado de `post.py`; `X_ENV_FILE` pode indicar outro caminho, e `post.py --env-file` permite especificá-lo diretamente. Não versione credenciais.

Revise o estado copiado: o exemplo contém um envio anterior, inclusive uma data. Ajuste `proximo` para o conselho desejado e, para começar sem histórico, use `null` em `ultimo_enviado` e `data_ultimo_envio`.

## Executar

Com o serif.sh rodando na porta 5173, teste:

```bash
python3 daily.py
python3 daily.py --dry-run
```

O dry-run gera e valida o PNG e consulta o usuário autenticado no X: **requer rede e credenciais válidas**, mas não envia mídia nem publica. Não avança o estado nem grava o log. Se o estado não existir, copia o modelo mesmo no dry-run.

Para publicar:

```bash
python3 daily.py --publish
```

Opções: `--estado /caminho/estado.json`, `--conselhos /caminho/conselhos.json` e `--url http://127.0.0.1:5173`. Os caminhos padrão ficam no diretório do script; caminhos fornecidos são relativos ao diretório atual. O log fica ao lado do script.

A imagem recebe o texto do conselho, autor e fonte. O post contém somente a imagem, sem a chave `text` no payload. O texto alternativo contém o número e o conselho na primeira linha, o autor na segunda e a fonte na terceira. O resumo JSON inclui `image_only_ok` (payload sem `text` e com IDs de mídia) e `alt_text`. Argumentos são passados diretamente, sem shell, com quebras de linha reais.

Em `--publish`, se `data_ultimo_envio` já for hoje em `America/Sao_Paulo`, termina sem renderizar nem publicar. Após sucesso, substitui o estado atomicamente com `proximo=n+1`, `ultimo_enviado=n` e a data de hoje, e acrescenta uma linha a `log.jsonl`. Falhas retornam código diferente de zero; a saída é JSON, sem credenciais. Ao terminar a lista, é necessário definir novos conselhos ou ajustar o estado.

Execute apenas uma instância por vez. A publicação no X e a gravação local não formam uma única transação: se houver interrupção após publicar e antes de salvar o estado, confira o X antes de repetir. Se o log falhar após salvar o estado, o estado continua avançado.

## Agendamento

Exemplo de crontab para as 8h de São Paulo em sistemas cujo cron suporta `CRON_TZ`:

```cron
CRON_TZ=America/Sao_Paulo
0 8 * * * cd /caminho/conselho-do-dia-x && /usr/bin/python3 daily.py --publish >> cron.log 2>&1
```

Se usar ambiente virtual, troque `/usr/bin/python3` pelo caminho absoluto de `.venv/bin/python`. Garanta que o cron encontre o Tesseract e o Chromium instalado para o mesmo usuário. O serif.sh precisa estar rodando no horário: sugere-se iniciá-lo via systemd, pm2 ou uma entrada `@reboot`. Em implementações sem `CRON_TZ`, configure o fuso do serviço de agendamento.

`.env`, `estado.json`, `out/`, `cron.log` e `log.jsonl` ficam fora do versionamento.
