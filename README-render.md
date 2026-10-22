# Renderização Editorial

O `render.py` abre Chromium headless com Playwright, seleciona Editorial pelo fragmento da URL e captura o download PNG gerado pelo próprio app (html-to-image). Se a exportação estiver indisponível, usa screenshot apenas do cartão. O código-fonte do SvelteKit não é alterado.

## Subir o app

```bash
cd /home/box/repos/serif-sh && npm install && npm run dev -- --port 5173 --host 127.0.0.1
```

## Uso

Em outro terminal, execute exatamente:

```bash
cd /workspace/serif-render
python3 render.py --text '8. Diga “obrigado” muitas vezes.' --author 'H. Jackson Brown, Jr.' --source 'Pequeno Manual de Instruções para a Vida'
```

Requer Python com `playwright`, Chromium do Playwright, Pillow e `tesseract` com idioma `por` instalados. Se o Chromium do Playwright não estiver disponível, o script procura Chromium/Chrome instalado no sistema. Se necessário, instale o navegador com `python3 -m playwright install chromium`.

Opções: `--n N` define o sufixo do arquivo (padrão: data local `AAAAMMDD`); `--url U` define o endereço do app (padrão: `http://127.0.0.1:5173`). Saída sempre relativa ao diretório do script: `out/conselho-<n>.png`. O sufixo aceita letras, números, `_` e `-`.

O app atual suporta `quote` e `author` em Base64 UTF-8 e `theme=editorial` no fragmento da URL. O script também confere os campos após carregar e os preenche se necessário. Como não há campo de fonte, acrescenta uma linha de fonte ao DOM do cartão, abaixo do autor, apenas na sessão do navegador. Requisições de analytics e para outros hosts são bloqueadas; fontes externas podem usar o fallback CSS do app.

Cada uma das até seis tentativas verifica:

- DOM: dimensões de rolagem de todos os elementos que contêm texto e seus ancestrais, ausência de ellipsis/line-clamp e caixas dos elementos e dos textos dentro do cartão.
- Área segura: caixas de todos os elementos com texto direto e retângulos dos trechos de texto dentro de uma margem de 6% por lado (96 px horizontais e 54 px verticais no PNG final).
- PNG: exatamente 1600×900 (16:9), razão entre 0,75 e 2,0 e tamanho estritamente menor que 5 MiB (5 × 1024 × 1024 bytes). O cartão tem 800×450 CSS px com exportação em escala 2; Pillow ajusta a imagem inteira, sem cortar texto, sobre canvas 1600×900 na cor de fundo do cartão e salva PNG otimizado.
- PNG: OCR com `tesseract -l por`, imagem ampliada em cinza e até três modos de segmentação. Compara palavras em minúsculas, sem acentos e separadas por pontuação (incluindo aspas tipográficas). Exige todas as ocorrências das palavras do texto, autor e fonte em uma mesma leitura OCR.

Se falhar, reduz fonte e padding via estilos do DOM (preservando o mínimo da margem segura), permite quebra das linhas e repete exportação e todas as verificações. O arquivo da última tentativa permanece para diagnóstico. OCR é uma verificação conservadora: erros de reconhecimento também causam falha.

A última linha do stdout é JSON com `path`, `tentativas`, `overflow_ok`, `ocr_ok`, `palavras_faltantes`, `width`, `height`, `bytes`, `aspect_ok`, `size_ok`, `safe_area_ok`, `safe_area_details`, método de exportação e detalhes de overflow (ou `error`). O `daily.py` também exige esses cinco indicadores e inclui dimensões, bytes e indicadores no JSON de resumo. Progresso vai para stderr. Código de saída `0` exige `overflow_ok`, `ocr_ok`, `aspect_ok`, `size_ok` e `safe_area_ok` verdadeiros; falha retorna `1`.

## Verificação neste ambiente

Execução validada em 22/10/2026 fora do sandbox — conselho do dia e texto longo (~270 caracteres) passaram na 1ª tentativa (DOM e OCR OK, export pelo download do app).

Observação: o app precisa estar rodando em `127.0.0.1:5173` antes de chamar o script.
