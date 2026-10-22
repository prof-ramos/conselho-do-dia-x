# Publicar PNG no X com texto opcional

Script Python 3 que usa somente a biblioteca padrão (`urllib`) e OAuth 1.0a de usuário, com assinatura HMAC-SHA1 implementada no próprio arquivo.

## Credenciais

Defina estas variáveis de ambiente:

- `X_CONSUMER_KEY`
- `X_CONSUMER_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

Valores ausentes são procurados em `.env` ao lado de `post.py` (ou no caminho definido por `X_ENV_FILE`), no formato `KEY=VALUE`. Use `--env-file /caminho/arquivo.env` para mudar o arquivo. O ambiente tem prioridade. São aceitos comentários em linhas iniciadas por `#` e valores entre aspas simples ou duplas; não há expansão de variáveis nem execução de comandos. Proteja o arquivo de credenciais com permissões restritas.

O script não imprime nem grava credenciais. Erros HTTP incluem status e corpo da resposta, sem headers, com os valores conhecidos das credenciais ocultados.

## Uso

Dry-run é o padrão. Valida texto opcional, texto alternativo e PNG e faz somente `GET /2/users/me` para confirmar o usuário autenticado. Requer rede e credenciais válidas; não envia a imagem nem cria posts.

```bash
python3 post.py --alt-text 'Conselho\nAutor\nFonte' --image ./imagem.png
python3 post.py --dry-run --text 'Prévia do post' --image ./imagem.png --env-file /caminho/arquivo.env
```

Para publicar explicitamente (faz upload da imagem e depois cria o post):

```bash
python3 post.py --publish --alt-text 'Conselho\nAutor\nFonte' --image ./imagem.png
```

`--dry-run` e `--publish` são mutuamente exclusivos. `--image` é obrigatório; `--text` é opcional. Texto omitido, vazio ou só com espaços gera um post somente com imagem, sem a chave `text` no JSON. `--alt-text` aceita até 1000 caracteres. A sequência literal `\n` em ambos os textos é convertida em quebra de linha antes da validação.

Ambos os modos limitam o texto opcional a 280 caracteres pela aproximação abaixo e exigem assinatura PNG válida e arquivo de até 5 MiB (5.242.880 bytes). A assinatura de oito bytes é verificada; o script não decodifica a imagem inteira.

A contagem é aproximada: URLs iniciadas por `http://` ou `https://` até o próximo espaço contam como 23 caracteres; o restante usa code points (`len`). Portanto, CJK e emoji não recebem peso 2 e sequências compostas ou pontuação ao fim de URLs podem diferir da contagem do X. Um texto aceito localmente ainda pode ser rejeitado pela API.

A saída de sucesso é JSON em stdout: no dry-run, contém `payload` com o JSON exato destinado a `POST /2/tweets` (ID substituído por `<media_id>`), `alt_text`, `image_only`, usuário, contagem do texto, caminho/tamanho da imagem e `would_publish: false`; na publicação, contém ID e URL do post. Erros são JSON em stderr e retornam código diferente de zero. As credenciais precisam permitir as operações solicitadas na API do X. Se o upload funcionar e a criação do post falhar, a mídia pode permanecer enviada; o script não repete operações automaticamente.

Quando `--alt-text` é informado, após o upload e antes de criar o post, o script usa o helper OAuth `request_json` para enviar `POST https://api.x.com/2/media/metadata` com `{"id": "<media_id>", "metadata": {"alt_text": {"text": "..."}}}`. Falha nessa etapa impede a criação do post. A saída da publicação também inclui `payload`, `alt_text` e `image_only`.
