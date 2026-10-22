# Publicar texto e PNG no X

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

Dry-run é o padrão. Valida texto e PNG e faz somente `GET /2/users/me` para confirmar o usuário autenticado. Requer rede e credenciais válidas; não envia a imagem nem cria posts.

```bash
python3 post.py --text 'Olá!\nSegunda linha.' --image ./imagem.png
python3 post.py --dry-run --text 'Prévia do post' --image ./imagem.png --env-file /caminho/arquivo.env
```

Para publicar explicitamente (faz upload da imagem e depois cria o post):

```bash
python3 post.py --publish --text 'Olá!\nSegunda linha.' --image ./imagem.png
```

`--dry-run` e `--publish` são mutuamente exclusivos. `--text` e `--image` são obrigatórios. A sequência literal `\n` no texto é convertida em quebra de linha.

Ambos os modos exigem texto não vazio, até 280 caracteres pela aproximação abaixo, assinatura PNG válida e arquivo de até 5 MiB (5.242.880 bytes). A assinatura de oito bytes é verificada; o script não decodifica a imagem inteira.

A contagem é aproximada: URLs iniciadas por `http://` ou `https://` até o próximo espaço contam como 23 caracteres; o restante usa code points (`len`). Portanto, CJK e emoji não recebem peso 2 e sequências compostas ou pontuação ao fim de URLs podem diferir da contagem do X. Um texto aceito localmente ainda pode ser rejeitado pela API.

A saída de sucesso é JSON em stdout: no dry-run, contém usuário, contagem do texto, caminho/tamanho da imagem e `would_publish: false`; na publicação, contém ID e URL do post. Erros são JSON em stderr e retornam código diferente de zero. As credenciais precisam permitir as operações solicitadas na API do X. Se o upload funcionar e a criação do post falhar, a mídia pode permanecer enviada; o script não repete operações automaticamente.
