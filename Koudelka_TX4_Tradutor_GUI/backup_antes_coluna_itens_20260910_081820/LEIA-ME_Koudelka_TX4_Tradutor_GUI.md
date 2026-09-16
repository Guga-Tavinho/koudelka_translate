# Koudelka TX4 Tradutor GUI

Interface gráfica para visualizar e traduzir as descrições de itens e as páginas de ajuda:

```text
MENU\ITEMS\001.TX4
MENU\MENUHELP.TX4
```

Ela mantém o formato binário do jogo e usa, nos itens, o padrão aprovado:
Arial preta, sem sombra, preservando os títulos originais dos blocos com título.

## Cores da fonte e previa

A previa agora decodifica a **paleta real (CLUT) de cada bloco**, tambem para itens.
Antes, as cores dos itens eram apenas ilustrativas: laranja RGB(208,160,80) e
sombra RGB(160,64,32). Essas cores nao eram gravadas pelo renderizador no TX4.
O arquivo mantinha a sua CLUT original, o que explicava a diferenca de cor.

O painel do bloco informa a cor nativa e se o pixel tem a flag de semitransparencia.
A cor final no jogo ainda depende da mistura com o fundo e da modulacao usada
pelo renderizador do PS1; a previa nao emula esses efeitos.

Ao gerar traduções de itens, a ferramenta escreve as letras no índice 1 da
paleta (preto nativo 0x8000), sem desenhar sombra. Não altera a paleta e recusa
a geração se esse índice não tiver o preto esperado. MENUHELP mantém seu texto
branco e sombra cinza: seu perfil não foi alterado.

O padrão vale para os blocos que têm texto no campo PT-BR. Blocos sem tradução
ou marcados SEM_TEXTO são copiados exatamente como estão no arquivo aberto;
não há conversão automática da sombra que já esteja gravada nessas imagens.
Para continuar a versão aprovada, abra **001_FONTE_PRETA_SEM_SOMBRA.TX4**.
O arquivo original não é sobrescrito.

Para fontes pretas, existe a opção **Fundo claro (somente na prévia)**. Ela troca
apenas a apresentacao dos pixels transparentes no programa, sem modificar o TX4.
Ao abrir um arquivo cuja entrada de fonte seja preta, esse fundo e ativado.
O preto nativo da paleta e 0x8000; 0x0000 e transparencia, nao uma tinta preta.

## MENUHELP.TX4 — suporte específico

Reabra o **MENUHELP.TX4 original** usando o mesmo `ABRIR_KOUDELKA_TX4_GUI.bat`.
A leitura antiga, feita pelas regras de itens, dividia esse arquivo em 17 blocos
incorretos. A leitura atual encontra as **9 páginas reais** pelos cabeçalhos TX41.

- Textura nativa: 256×256; área textual observada: **256×190**.
- Passo entre páginas do original: `0x8800`; pixels em `+0x30`.
- As linhas 190–255 são preenchimento e ficam intactas na geração.
- Traduza a página completa no campo PT-BR, **incluindo o título**. Não há uma
  faixa reservada para nome de item: a substituição começa em Y=0.
- Arial 11 px, espaçamento de 13 px, até 14 linhas, largura de até 248 px,
  texto centralizado, sem antialias e com sombra de 1 pixel.
- As quebras manuais e linhas vazias são respeitadas. A ferramenta não reconstrói
  automaticamente tabelas/colunas: confira a organização na prévia.
- Texto branco, sombra cinza e fundo transparente nativo (mostrado em preto),
  usando a paleta de cada página. Não utiliza as cores alaranjadas dos itens.
- Texto que não cabe bloqueia a geração; não é cortado silenciosamente.
- Zoom **Ajustar** mostra toda a página. Em 1x/2x/3x use as barras de rolagem.
- Cabeçalhos, paletas, preenchimento e páginas não traduzidas permanecem intactos.

Se houver CSV da leitura antiga com 17 blocos, não o importe como se representasse
as 9 páginas: os números não correspondem. A ferramenta recusa essa associação.
Copie os textos aproveitáveis para as páginas corretas e salve um novo CSV.
Os novos CSVs incluem perfil e endereço de bloco para conferir a correspondência.

A geração é para um novo nome, por exemplo `MENUHELP_TRADUZIDO_ARIAL.TX4`.
Reinjete-o no caminho interno **MENU/MENUHELP.TX4**, não no caminho de itens.
Teste o resultado no jogo após a reinjeção.

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

As regras desta seção se referem aos arquivos de itens, não ao MENUHELP.

- o título/nome original permanece intocado;
- somente a área da descrição é apagada;
- descrições normais começam em `Y=30` e aceitam 6 linhas;
- nos títulos adicionais listados abaixo, se já existir descrição na faixa
  `Y=18..29`, a edição começa em `Y=18` e aceita 7 linhas;
- Arial 11 px;
- distância vertical de 15 px;
- texto sem antialias;
- preto nativo, sem sombra.

Essa regra vale para os blocos 1–114 e também para 115, 154, 201, 206, 211,
215–222 e 224–230. Esses blocos adicionais incluem títulos como `Guard's Diary`,
`Research Notes`, `Stone Tablet`, `Daniel's Arm` e `Relief Piece`.
Nesses blocos, preencha o campo PT-BR somente com a descrição: o título já está
na imagem e será preservado. O limite de linhas aparece ao selecionar o bloco.

### Páginas de continuação

- a imagem textual original é apagada por inteiro;
- a tradução começa em `Y=0`;
- máximo de 8 linhas;
- as mesmas configurações de Arial preta sem sombra.

### Estrutura binária dos itens

- no original de itens, bloco a cada 18.432 bytes (`0x4800`);
- imagem visível de 256×128;
- codec 4bpp linear reverse-order;
- início dos pixels em `+0x30`;
- os primeiros `0x30` bytes de cada bloco, incluindo cabeçalho/CLUT, são preservados;
- o TX4 final mantém exatamente o tamanho do original.

O leitor agora segue os cabeçalhos reais de cada textura, em vez de dividir
qualquer TX4 em blocos fixos. Layouts não reconhecidos são recusados.

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
tx4_profile
block_offset
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
