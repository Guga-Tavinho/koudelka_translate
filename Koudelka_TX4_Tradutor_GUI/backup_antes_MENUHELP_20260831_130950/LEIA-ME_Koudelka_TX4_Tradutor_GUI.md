# Koudelka TX4 Tradutor GUI

Interface gráfica para visualizar e traduzir as descrições contidas em:

```text
MENU\ITEMS\001.TX4
```

Ela reproduz o comportamento da `koudelka_tx4_tool_v9_arial.py` que foi testada durante o projeto.

## Requisitos

- Windows 10 ou 11;
- Python 3.10 ou mais recente;
- Pillow;
- Arial em `C:\Windows\Fonts\arial.ttf`;
- EasyOCR e PyTorch para CPU.

Execute:

```cmd
INSTALAR_DEPENDENCIAS_OCR_LOCAL.bat
```

Não é necessária conta, chave de API ou pagamento. Na primeira utilização do OCR, o
EasyOCR baixa gratuitamente o modelo de reconhecimento do idioma selecionado. Depois
disso o OCR funciona offline e as imagens permanecem no computador. A instalação do
PyTorch ocupa mais espaço que um OCR tradicional, mas oferece reconhecimento melhor
para as letras pixeladas do jogo.

## Como abrir

Coloque estes arquivos na mesma pasta:

```text
001.TX4
ITMTBL.ITM
koudelka_tx4_tradutor_gui.py
```

O `ITMTBL.ITM` é opcional, mas permite que a interface mostre nomes como `Bread`, `Cheese` e `Dried_Food`.

Execute:

```cmd
python koudelka_tx4_tradutor_gui.py
```

Também é possível abrir diretamente o TX4 e um CSV:

```cmd
python koudelka_tx4_tradutor_gui.py "001.TX4" "koudelka_230_TRADUZIDO.csv"
```

## Fluxo recomendado

1. Clique em **Abrir TX4** e selecione o `001.TX4` original.
2. Se você já tem o CSV antigo, clique em **Importar CSV**.
3. Escolha **Inglês** ou **Japonês** ao lado dos botões de OCR.
4. Se não tiver o CSV, use **OCR local selecionado** ou **OCR local de todos** para preencher o texto original.
5. Selecione cada bloco na lista.
6. Confira a imagem original e revise o texto reconhecido.
7. Digite a tradução em **Tradução PT-BR**.
8. Confira a prévia Arial e o contador de linhas.
9. Salve o trabalho com **Salvar CSV**.
10. Clique em **Gerar TX4**.

A interface não sobrescreve o `001.TX4` original.

## OCR local gratuito

- usa EasyOCR sob licença Apache 2.0;
- não envia as imagens para a internet;
- não cobra por bloco ou por imagem;
- processa somente com a CPU, portanto o OCR dos 230 blocos pode demorar;
- detecta automaticamente se a descrição original começa em `Y=18` ou `Y=30`;
- documentos são reconhecidos como um único campo de texto;
- o resultado continua sendo texto de OCR e deve ser revisado antes da tradução.

## Regras aplicadas automaticamente

### Blocos com título próprio

- o título/nome original permanece intocado;
- somente a área da descrição é apagada;
- descrições normais começam em `Y=30` e aceitam 6 linhas;
- descrições longas que já começam em `Y=18` aceitam 7 linhas;
- Arial 11 px;
- distância vertical de 15 px;
- texto sem antialias;
- sombra de 1 px.

Essa regra vale para os blocos 1–114 e também para 115, 154, 201, 206, 211,
215–222 e 224–230. Esses blocos adicionais incluem títulos como `Guard's Diary`,
`Research Notes`, `Stone Tablet`, `Daniel's Arm` e `Relief Piece`.

### Páginas de continuação

- a imagem textual original é apagada por inteiro;
- a tradução começa em `Y=0`;
- máximo de 8 linhas;
- as mesmas configurações de Arial e sombra.

### Estrutura binária

- bloco fixo de 18.432 bytes (`0x4800`);
- imagem visível de 256×128;
- codec 4bpp linear reverse-order;
- início dos pixels em `+0x30`;
- os primeiros `0x30` bytes de cada bloco, incluindo cabeçalho/CLUT, são preservados;
- o TX4 final mantém exatamente o tamanho do original.

Se qualquer tradução ultrapassar o limite, a geração é interrompida e a interface lista os blocos que precisam ser encurtados.

## CSV

O projeto é salvo em UTF-8 com estas colunas:

```text
block
original_name
title_ocr
description_original_ocr
description_pt
status
translation_status
```

A interface também importa os CSVs antigos do projeto, inclusive os que usam `original_text` ou `translation_pt`.

Estados disponíveis:

```text
PENDENTE
TRADUZIDO
SEM_TEXTO
```

## Atalhos

```text
Ctrl+O       abrir TX4
Ctrl+S       salvar CSV
Ctrl+G       gerar TX4
Ctrl+↑/↓     bloco anterior/próximo
```

## Geração sem interface

Para automação ou teste:

```cmd
python koudelka_tx4_tradutor_gui.py --render-csv "001.TX4" "koudelka_230_TRADUZIDO.csv" "001_TRADUZIDO_ARIAL.TX4"
```

Com outra cópia de Arial:

```cmd
python koudelka_tx4_tradutor_gui.py --render-csv "001.TX4" "traducao.csv" "001_TRADUZIDO_ARIAL.TX4" --font "C:\Windows\Fonts\arial.ttf"
```

## Reinjeção no BIN

Depois de conferir que o TX4 gerado tem o mesmo tamanho do original, use o `psxinject` no MSYS2:

```bash
./src/psxinject.exe -v \
"/c/Users/sistemas2/Desktop/Koudelka (Disc 1)/ORIGINAL/Koudelka (Disc 1).bin" \
"MENU/ITEMS/001.TX4" \
"/c/Users/sistemas2/Desktop/Koudelka (Disc 1)/MENU/ITEMS/001_TRADUZIDO_ARIAL.TX4"
```

Mantenha sempre uma cópia não modificada do BIN original.
