# Koudelka PS1 Translation and Modding Tools

[Português](#português) | [English](#english)

This repository contains source-code tools created to inspect, translate, rebuild, and inject resources used by the PlayStation version of **Koudelka**.

Este repositório contém ferramentas em código-fonte criadas para inspecionar, traduzir, reconstruir e injetar recursos usados na versão de PlayStation de **Koudelka**.

> [!IMPORTANT]
> This is a source-only project. It does not provide a game image, original game files, BIOS files, compiled releases, or copyrighted assets.
>
> Este é um projeto distribuído apenas em código-fonte. Ele não fornece imagem do jogo, arquivos originais, BIOS, versões compiladas ou recursos protegidos por direitos autorais.

---

# Português

## Informações importantes sobre as versões do jogo

1. A versão americana não contém legendas nas CGIs/cutscenes renderizadas em tempo real armazenadas em MCF.
2. Apenas a versão japonesa possui essas legendas.
3. Por isso, a ferramenta de legendas MCF deve usar os MCFs japoneses como base. O MCF armazena as legendas como imagens indexadas, não como texto comum.

As ferramentas foram desenvolvidas e testadas principalmente no Windows 10/11 de 64 bits com imagens BIN/CUE de discos obtidos legalmente pelo próprio usuário.

## Localização dos arquivos dentro da imagem BIN

Os caminhos abaixo são caminhos internos do disco depois da extração:

| Conteúdo | Caminho interno |
|---|---|
| MCF — CGIs/cutscenes renderizadas em tempo real | <code>\MOVIE\*.MCF</code> |
| STR — CGIs/cutscenes pré-renderizadas | <code>\MOVIE\*.STR</code> |
| Descrições e imagens dos itens | <code>\MENU\ITEMS\001.TX4</code> |
| Imagens dos menus principais e telas DATA | <code>\DATA\*.TEX</code> |
| Executáveis e menus internos | <code>\BIN\*.BIN</code> e <code>\MENU\*.BIN</code> |
| Imagens de inserir/trocar disco | <code>\DISK\*.TX8</code> |
| Imagens de Game Over | <code>\MENU\GAMEOVER\*.TX8</code> |
| Textos de salas, portas, interação e obtenção de itens | <code>\MDT\*.MDT</code> |

Os nomes podem aparecer em maiúsculas ou minúsculas dependendo da ferramenta utilizada para extrair o disco.

## Ferramentas incluídas

### AVI to STR

Converte um AVI editado para o formato STR de PlayStation 1 usando psxavenc.

- aceita um arquivo ou uma pasta inteira;
- recria a estrutura relativa das subpastas;
- normaliza o vídeo com FFmpeg;
- usa vídeo MDEC v2, 320×240 e 15 FPS;
- usa áudio XA de 37.800 Hz, estéreo e 4 bits;
- compara o número de quadros com o STR original através do jPSXdec;
- tenta ajustar automaticamente diferenças de quadros;
- verifica se o arquivo novo cabe na quantidade de setores do STR original;
- não altera o AVI nem o STR original.

Dependências: Python, Tkinter, FFmpeg, ffprobe, psxavenc, Java e jPSXdec.

Entrada/saída principal: <code>\MOVIE\*.STR</code>.

### BIN Extrator

Interface gráfica para extrair uma imagem CUE/BIN usando psxrip.

- recomenda selecionar o CUE;
- valida os arquivos BIN referenciados pelo CUE;
- executa o psxrip no diretório correto do CUE;
- preserva LBNs através da opção <code>-l</code>;
- gera a árvore extraída, um catálogo CAT e uma área de sistema SYS;
- mantém a imagem de origem somente para leitura;
- inclui suporte à modificação do modo de disco 16 descrita neste README.

Dependências: Python, Tkinter e uma compilação modificada do psxrip.

### Inject files

Injetor genérico para substituir arquivos arbitrários dentro de uma imagem BIN.

- aceita um ou vários arquivos;
- sugere o caminho interno com base nas pastas do projeto;
- permite corrigir manualmente o caminho interno;
- remove sufixos locais como <code>_PTBR</code>, <code>_TRADUZIDO</code> e <code>_FINAL</code> ao sugerir o nome interno;
- pode trabalhar em uma cópia da imagem;
- registra o resultado de cada operação;
- usa psxinject através do MSYS2.

Dependências: Python, Tkinter, MSYS2/Bash e psxinject.

### Interface Menu (bins)

Localiza e edita textos gráficos dos menus e executáveis internos.

- edita opções do menu principal e comandos de batalha;
- edita indicadores como HP, MP, LV e Time;
- edita mensagens de obtenção/descarte, magia, Continue/Load e Save;
- analisa <code>BIN\*.BIN</code>, <code>MENU\*.BIN</code> e executáveis SLUS;
- oferece sugestões PT-BR, importação/exportação CSV e prévia;
- respeita a capacidade original de cada texto;
- faz auditoria byte a byte antes de salvar;
- pode gerar uma cópia adaptada de <code>MENU\FONTS.FT4</code> para acentos e cedilha;
- preserva os arquivos originais.

Ela não edita nomes ou descrições de itens do <code>001.TX4</code>.

Dependências: Python, Tkinter e Pillow.

### jpsxdec_v2.1-beta

jPSXdec é uma ferramenta externa para analisar e converter mídia de PlayStation 1. Neste projeto ela é usada principalmente para:

- analisar STRs;
- conferir a quantidade de quadros;
- extrair ou converter áudio CD-ROM XA de determinados MCFs.

Dependência: Java 8 ou superior.

O jPSXdec não é código deste projeto e possui licença própria para uso não comercial. Consulte a seção de licenças antes de redistribuí-lo.

### Koudelka_MCF_Audio_Extractor_GUI

Extrai áudio de um MCF individual ou de uma pasta inteira.

- reconhece SPU-ADPCM em blocos STRM e decodifica esse formato internamente;
- reconhece áudio CD-ROM XA, como o encontrado em <code>ENDING.MCF</code>;
- usa jPSXdec para áudio CD-ROM XA;
- preserva a estrutura de subpastas;
- gera WAVs e um relatório CSV;
- respeita o tamanho real declarado no cabeçalho do STRM para evitar silêncio adicional.

Dependências: Python e Tkinter. Java e jPSXdec são necessários para MCFs com áudio CD-ROM XA.

### Koudelka_MCF_Audio_Injector_GUI

Substitui o áudio STRM das cenas SCxx dentro de um MCF.

- recebe o MCF original e um WAV PCM;
- espera normalmente WAV de 16 bits, estéreo e 44.100 Hz;
- completa com silêncio quando o áudio é menor;
- recusa áudio maior que a capacidade original;
- usa o interleave correto do STRM;
- preserva flags ADPCM e toda a estrutura não relacionada ao áudio;
- gera um novo MCF e um relatório;
- nunca modifica o MCF original.

Esta ferramenta não injeta áudio no <code>ENDING.MCF</code>, pois ele usa CD-ROM XA.

Dependências: Python, Tkinter e psxavenc.

### Koudelka_MCF_Subtitle_Tool_GUI__TTF

Extrai, revisa, traduz e reconstrói as legendas gráficas dos MCFs japoneses.

- abre um MCF ou uma pasta inteira;
- extrai as legendas para CSV;
- permite pesquisar e substituir palavras em massa;
- marca graficamente os textos modificados;
- sinaliza legendas encontradas por OCR;
- importa e exporta traduções em CSV;
- gera um MCF ou todos os MCFs de uma pasta;
- preserva IDs, triplets e metadados;
- cria novos arquivos sem alterar os MCFs originais.

Modos de renderização:

- **Texto CRT nítido:** Tahoma Regular 12, rasterização monocromática direta em 300×39, sem LANCZOS, antialiasing, cinza, contorno ou sombra;
- **TTF suavizado:** modo legado com superamostragem;
- **Fonte nativa FT4:** mantém a aparência original do jogo.

O MCF sempre armazena bitmaps. A ferramenta renderiza o texto externamente e grava a imagem indexada no formato esperado pelo jogo.

Dependências: Python, Tkinter, Pillow e NumPy. Para OCR: pytesseract, Tesseract OCR e <code>jpn.traineddata</code>.

Para o modo CRT, selecione a Tahoma instalada pelo Windows em <code>C:\Windows\Fonts\tahoma.ttf</code>. Não redistribua os arquivos Tahoma no repositório.

### Koudelka_TX4_Tradutor_GUI

Visualiza, traduz e reconstrói:

~~~text
\MENU\ITEMS\001.TX4
\MENU\MENUHELP.TX4
~~~

Recursos principais:

- mostra cada bloco e sua paleta real;
- permite OCR do título e da descrição;
- importa e exporta CSV;
- preserva títulos originais quando necessário;
- usa Arial preta e sem sombra nas descrições dos itens;
- limita a descrição à coluna esquerda para não cobrir a imagem do item;
- aplica quebras automáticas de linha;
- preserva cabeçalhos, CLUTs, preenchimento e tamanho total;
- possui tratamento específico para as nove páginas reais do MENUHELP;
- recusa textos que não cabem em vez de cortá-los;
- nunca sobrescreve o TX4 original.

Dependências atuais: Python 3.10+, Tkinter e Pillow. O OCR opcional chama o executável Tesseract diretamente.

> [!NOTE]
> O instalador antigo desta pasta ainda menciona EasyOCR e PyTorch, mas o código atual não os utiliza. Eles não são necessários para executar a versão atual.

### MDT Inject

Injeta um MDT ou uma pasta estruturada de MDTs na imagem BIN.

- preserva caminhos relativos;
- permite configurar o prefixo interno;
- trabalha em uma cópia do BIN por padrão;
- pode interromper no primeiro erro ou continuar o lote;
- gera log detalhado;
- não altera os MDTs de entrada.

Dependências: Python, Tkinter, MSYS2/Bash e psxinject.

### MDT Tradutor

Lê, traduz, valida e gera MDTs.

- abre um arquivo ou uma pasta completa;
- localiza os blocos de texto;
- mostra capacidade e bytes utilizados;
- normaliza caracteres PT-BR suportados;
- importa e exporta CSV;
- filtra estados e textos;
- bloqueia entradas que excedem o espaço disponível;
- gera novos MDTs preservando a estrutura;
- não altera os MDTs originais.

A tradução/geração usa somente Python e Tkinter. Os módulos de injeção presentes na pasta também precisam de MSYS2/Bash e psxinject.

Entrada/saída principal: <code>\MDT\*.MDT</code>.

### TEX Importer

Converte PNG para TEX usando um TEX original como molde.

- exige PNG com as dimensões esperadas;
- preserva a paleta original ou gera uma nova paleta PS1 BGR555 de até 256 cores;
- preserva o comportamento STP da paleta;
- possui modo especial para montar uma tela 320×240 em <code>BACK1.TEX</code> e <code>BACK2.TEX</code>;
- usa uma paleta compartilhada ao gerar BACK1/BACK2;
- oferece prévia antes/depois e recarregamento automático;
- preserva cabeçalho e tamanho;
- gera um novo TEX e relatório JSON.

Dependências: Python, Tkinter e Pillow.

Entrada/saída principal: <code>\DATA\*.TEX</code>.

### TEX Viewer

Visualiza e exporta TEX para PNG.

- abre um TEX ou uma pasta;
- exibe a paleta PS1 BGR555;
- possui controles de zoom e transparência;
- exporta um arquivo ou todos em lote;
- combina automaticamente <code>BACK1.TEX</code> e <code>BACK2.TEX</code> em uma tela 320×240;
- é somente leitura e não modifica TEX.

Dependências: Python, Tkinter e Pillow.

### tile_molester_021

Tile Molester é uma ferramenta Java externa e genérica para visualizar e editar gráficos em blocos/tile graphics de arquivos binários. Ela pode auxiliar na inspeção manual de formatos gráficos, mas não conhece automaticamente a estrutura específica do Koudelka.

Dependência: Java. Essa ferramenta possui projeto e licença próprios e não faz parte do código original deste repositório.

### TX8 Extrator

Extrai, visualiza e reinjeta imagens em arquivos TX8.

- abre um TX8 ou uma pasta inteira;
- reconhece arquivos com um ou vários blocos;
- exporta visualizações linear, painéis e tela 320×240 quando aplicável;
- reconhece variantes NEWF0 e MENUPAD;
- preserva paleta, cabeçalhos, metadados, padding e bit STP;
- importa PNG em uma imagem específica;
- importa vários PNGs de uma só vez usando o número inicial do nome;
- permite navegar por Anterior/Próxima nas prévias;
- reúne várias substituições em um único TX8 novo;
- recusa dimensões, transparência ou layouts incompatíveis;
- não altera o TX8 nem os PNGs originais.

Exemplos de associação em lote:

~~~text
001_tela_320x240_PTBR.png -> imagem 001
002_tela_320x240_PTBR.png -> imagem 002
005_linear.png            -> imagem 005
~~~

Dependências: Python 3.10+, Tkinter e Pillow.

Arquivos comuns: <code>\DISK\*.TX8</code> e <code>\MENU\GAMEOVER\*.TX8</code>.

## Dependências

### Requisitos básicos

- Windows 10 ou Windows 11, 64 bits;
- Python 3.10 ou superior;
- pip;
- Tcl/Tk e Tkinter, normalmente incluídos no instalador oficial do Python para Windows;
- uma imagem BIN/CUE obtida legalmente pelo usuário.

Na instalação do Python, marque **Add Python to PATH** e mantenha o componente Tcl/Tk selecionado.

### Pacotes Python

Crie um ambiente virtual na raiz do repositório:

~~~bat
py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install Pillow numpy pytesseract
~~~

Pillow é usado pelas ferramentas gráficas TEX, TX4, TX8, Interface Menu e MCF. NumPy e pytesseract são necessários pela ferramenta de legendas MCF.

### Programas externos

| Dependência | Utilizada por | Observação |
|---|---|---|
| PSXImager/psxrip | BIN Extrator | Deve ser compilado com a modificação do modo 16 |
| PSXImager/psxinject | Inject files e MDT Inject | Substitui arquivos dentro da BIN |
| MSYS2/Bash | Injetores | Necessário pelo fluxo atual dos scripts de injeção |
| FFmpeg e ffprobe | AVI to STR | Normalização e análise de vídeo/áudio |
| psxavenc | AVI to STR e MCF Audio Injector | Codificação MDEC, XA e SPU-ADPCM |
| Java 8+ | jPSXdec e Tile Molester | Runtime Java |
| jPSXdec 2.1 | AVI to STR e MCF Audio Extractor | Análise de STR e conversão XA |
| Tesseract OCR | MCF Subtitle Tool e TX4 | OCR local |
| <code>jpn.traineddata</code> | OCR de MCF japonês | Deve ficar na pasta tessdata do Tesseract |
| Arial | TX4 | Normalmente em <code>C:\Windows\Fonts\arial.ttf</code> |
| Tahoma Regular | MCF CRT | Normalmente em <code>C:\Windows\Fonts\tahoma.ttf</code> |

Depois da instalação, FFmpeg, ffprobe, Java e Tesseract podem ser colocados no PATH ou selecionados manualmente nas interfaces que oferecem esse campo.

## Modificação do psxrip para o modo de disco 16

Na imagem japonesa analisada, libcdio retorna o modo de disco numérico 16. O psxrip original interrompe a execução porque esse valor não pertence à lista de modos reconhecidos.

A modificação altera apenas essa validação: em vez de lançar uma exceção, o programa mostra um aviso e continua:

~~~text
++ WARN: Unknown disc mode 16; continuing anyway
~~~

Substituição aplicada em <code>src/psxrip.cpp</code>:

~~~cpp
switch (discMode) {
    case CDIO_DISC_MODE_CD_DATA:
    case CDIO_DISC_MODE_CD_XA:
    case CDIO_DISC_MODE_CD_MIXED:
        break;

    default:
        cdio_warn("Unknown disc mode %d; continuing anyway", discMode);
        break;
}
~~~

As verificações seguintes continuam ativas. O psxrip ainda confirma a primeira faixa, o formato de dados/XA e a presença de um sistema de arquivos ISO 9660. Portanto, o aviso não transforma qualquer arquivo arbitrário em uma imagem válida.

O arquivo <code>BIN Extrator\psxrip_modo16.cpp</code> pode ser mantido como referência da alteração. Para redistribuição sob GPL, ele não substitui o código-fonte correspondente completo do PSXImager.

### Compilando no MSYS2/MinGW64

Instale MSYS2 e, no terminal **MSYS2 MinGW x64**, instale as dependências:

~~~bash
pacman -S --needed git make autoconf-wrapper automake-wrapper \
  mingw-w64-x86_64-gcc mingw-w64-x86_64-pkgconf \
  mingw-w64-x86_64-libcdio mingw-w64-x86_64-vcdimager
~~~

Depois:

~~~bash
git clone https://github.com/cebix/psximager.git
cd psximager
./bootstrap
./configure
make
~~~

Aplique a modificação acima antes de executar <code>make</code>. Coloque o <code>src/psxrip.exe</code> compilado ao lado de <code>bin_extrator_gui.py</code>. O <code>src/psxinject.exe</code> pode ser selecionado nos injetores.

Como este repositório não publica versões compiladas, cada usuário deve compilar essas ferramentas externas ou obtê-las nos respectivos projetos, respeitando suas licenças.

## Executando as ferramentas

Ative o ambiente virtual e execute o script principal da ferramenta desejada. Os arquivos BAT existentes também podem ser usados quando o Python estiver no PATH.

Exemplos:

~~~bat
python "BIN Extrator\bin_extrator_gui.py"
python "AVI to STR\koudelka_avi_to_str_gui.py"
python "Inject files\koudelka_inject_arquivo_gui.py"
python "Interface Menu (bins)\koudelka_interface_gui.py"
python "Koudelka_MCF_Audio_Extractor_GUI\koudelka_mcf_audio_extractor_gui.py"
python "Koudelka_MCF_Audio_Injector_GUI\koudelka_mcf_audio_injector_gui.py"
python "Koudelka_MCF_Subtitle_Tool_GUI__TTF\koudelka_legendas_gui_v6.py"
python "Koudelka_TX4_Tradutor_GUI\koudelka_tx4_tradutor_gui.py"
python "MDT Inject\koudelka_inject_mdt_mass_v3_msys2.py"
python "MDT Tradutor\koudelka_mdt_gui.py"
python "TEX Importer\koudelka_png_to_tex_gui.py"
python "TEX Viewer\koudelka_tex_viewer_gui.py"
python "TX8 Extrator\koudelka_tx8_gui.py"
java -jar "jpsxdec_v2.1-beta\jpsxdec.jar"
java -jar "tile_molester_021\tilemolester.jar"
~~~

## Fluxo recomendado

1. Faça uma cópia de segurança da imagem BIN/CUE.
2. Extraia o disco com o BIN Extrator e mantenha a opção de LBNs ativada.
3. Edite ou reconstrua os arquivos com a ferramenta correspondente.
4. Salve sempre em uma pasta ou nome novo.
5. Injete os arquivos gerados em uma cópia da BIN.
6. Teste a imagem em emulador antes de gravar mídia ou substituir qualquer backup.

## Arquivos que não devem ser enviados ao GitHub

- imagens <code>.BIN</code>, <code>.CUE</code>, <code>.ISO</code> ou BIOS;
- arquivos originais extraídos do jogo;
- MCF, MDT, STR, TX4, TX8, TEX, FT4 ou outros recursos pertencentes ao jogo;
- <code>tahoma.ttf</code> e <code>tahomabd.ttf</code>;
- executáveis e JARs de terceiros em um repositório declarado como source-only;
- logs, caches, relatórios e configurações com caminhos pessoais;
- pastas de backup e resultados gerados.

Exemplo inicial de <code>.gitignore</code>:

~~~gitignore
__pycache__/
*.py[cod]
.venv/
*.log
*_settings.json
backup_*/
*.BIN
*.bin
*.CUE
*.cue
*.ISO
*.iso
*.MCF
*.mcf
*.MDT
*.mdt
*.STR
*.str
*.TX4
*.tx4
*.TX8
*.tx8
*.TEX
*.tex
*.FT4
*.ft4
*.ttf
*.otf
*.exe
*.jar
~~~

Se forem necessários arquivos de teste, use somente amostras sintéticas criadas para os testes e que não contenham dados do jogo.

## Licenças e redistribuição

O autor do repositório deve adicionar uma licença para o código Python original. Se o repositório incluir uma versão modificada do código do PSXImager, a opção mais simples é licenciar o conjunto compatível sob GPL-2.0-or-later, preservando avisos individuais de componentes externos.

- [PSXImager](https://github.com/cebix/psximager) — GPL-2.0-or-later. Uma distribuição modificada deve preservar a licença e oferecer o código-fonte correspondente completo.
- [psxavenc](https://github.com/WonderfulToolchain/psxavenc) — licença zlib.
- [FFmpeg](https://ffmpeg.org/legal.html) — LGPL ou GPL, conforme a configuração da compilação.
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — Apache-2.0.
- [jPSXdec](https://github.com/m35/jpsxdec/blob/readme/jpsxdec/doc/LICENSE.txt) — licença própria não comercial.
- Pillow, NumPy e pytesseract preservam suas respectivas licenças e avisos quando redistribuídos.
- As fontes Tahoma fornecidas com o Windows não devem ser copiadas para o repositório. Consulte o [FAQ de redistribuição de fontes da Microsoft](https://learn.microsoft.com/en-us/typography/fonts/font-faq).

Mantenha um arquivo <code>THIRD_PARTY_NOTICES.md</code> com os projetos, versões, links e licenças de todas as dependências externas.

## Aviso

Este projeto é uma ferramenta independente de pesquisa, tradução e modificação. Ele não é afiliado nem endossado pelos detentores dos direitos de Koudelka, Sacnoth, SNK ou seus distribuidores. Use somente arquivos obtidos de uma cópia do jogo que você possui e respeite a legislação aplicável em sua região.

---

# English

## Important information about game versions

1. The US version does not contain subtitles for real-time rendered CGI/cutscene sequences stored in MCF files.
2. Only the Japanese version contains these subtitles.
3. Therefore, the MCF subtitle tool must use Japanese MCF files as its base. MCF subtitles are stored as indexed images, not as ordinary text strings.

The tools were developed and tested primarily on 64-bit Windows 10/11 with BIN/CUE images created from legally obtained discs owned by the user.

## File locations inside the BIN image

The paths below are internal disc paths after extraction:

| Content | Internal path |
|---|---|
| MCF — real-time rendered CGI/cutscene sequences | <code>\MOVIE\*.MCF</code> |
| STR — pre-rendered CGI/cutscene sequences | <code>\MOVIE\*.STR</code> |
| Item descriptions and images | <code>\MENU\ITEMS\001.TX4</code> |
| Main menu and DATA screen images | <code>\DATA\*.TEX</code> |
| Internal executables and menus | <code>\BIN\*.BIN</code> and <code>\MENU\*.BIN</code> |
| Insert/change disc images | <code>\DISK\*.TX8</code> |
| Game Over images | <code>\MENU\GAMEOVER\*.TX8</code> |
| Room, door, interaction, and item pickup text | <code>\MDT\*.MDT</code> |

Names may appear in upper or lower case depending on the disc extraction tool.

## Included tools

### AVI to STR

Converts an edited AVI into the PlayStation 1 STR format through psxavenc.

- accepts one file or a complete folder;
- recreates the relative subfolder structure;
- normalizes video through FFmpeg;
- uses MDEC v2 video at 320×240 and 15 FPS;
- uses 37,800 Hz, 4-bit stereo XA audio;
- compares frame counts against the original STR through jPSXdec;
- attempts to correct frame-count differences automatically;
- verifies that the new file fits in the original STR sector allocation;
- never modifies the source AVI or original STR.

Dependencies: Python, Tkinter, FFmpeg, ffprobe, psxavenc, Java, and jPSXdec.

Main input/output path: <code>\MOVIE\*.STR</code>.

### BIN Extractor

Graphical interface for extracting a CUE/BIN image through psxrip.

- recommends selecting the CUE file;
- validates every BIN referenced by the CUE;
- runs psxrip from the correct CUE directory;
- preserves LBNs through the <code>-l</code> option;
- creates the extracted tree, a CAT catalog, and a SYS system-area file;
- keeps the source image read-only;
- supports the disc mode 16 modification documented in this README.

Dependencies: Python, Tkinter, and a modified psxrip build.

### Inject files

Generic injector for replacing arbitrary files inside a BIN image.

- accepts one or multiple files;
- suggests the internal path from the project folder structure;
- lets the user correct the internal path;
- removes local suffixes such as <code>_PTBR</code>, <code>_TRADUZIDO</code>, and <code>_FINAL</code> when suggesting the internal name;
- can work on a copy of the image;
- logs every operation;
- invokes psxinject through MSYS2.

Dependencies: Python, Tkinter, MSYS2/Bash, and psxinject.

### Interface Menu (bins)

Finds and edits graphical strings in menus and internal executables.

- edits main-menu options and battle commands;
- edits HP, MP, LV, and Time labels;
- edits item, magic, Continue/Load, and Save messages;
- scans <code>BIN\*.BIN</code>, <code>MENU\*.BIN</code>, and SLUS executables;
- offers PT-BR suggestions, CSV import/export, and previews;
- respects the original capacity of every string;
- performs a byte-for-byte audit before saving;
- can generate an adapted <code>MENU\FONTS.FT4</code> for accented characters;
- preserves all source files.

It does not edit item names or descriptions from <code>001.TX4</code>.

Dependencies: Python, Tkinter, and Pillow.

### jpsxdec_v2.1-beta

jPSXdec is an external PlayStation 1 media analysis and conversion utility. This project uses it mainly to:

- analyze STR files;
- verify frame counts;
- extract or convert CD-ROM XA audio from some MCF files.

Dependency: Java 8 or newer.

jPSXdec is not part of this project's original code and has its own non-commercial license. Read the licensing section before redistributing it.

### Koudelka_MCF_Audio_Extractor_GUI

Extracts audio from one MCF or a complete folder.

- recognizes SPU-ADPCM in STRM blocks and decodes it internally;
- recognizes CD-ROM XA audio such as the audio in <code>ENDING.MCF</code>;
- uses jPSXdec for CD-ROM XA;
- preserves relative subfolders;
- generates WAV files and a CSV report;
- respects the actual STRM size declared by its header, avoiding added silence.

Dependencies: Python and Tkinter. Java and jPSXdec are required for MCF files containing CD-ROM XA audio.

### Koudelka_MCF_Audio_Injector_GUI

Replaces STRM audio in SCxx MCF scenes.

- accepts an original MCF and a PCM WAV;
- normally expects 16-bit, stereo, 44,100 Hz WAV input;
- pads shorter audio with silence;
- rejects audio larger than the original capacity;
- uses the correct STRM interleave;
- preserves ADPCM flags and all unrelated MCF data;
- creates a new MCF and a report;
- never modifies the original MCF.

It does not inject audio into <code>ENDING.MCF</code>, which uses CD-ROM XA.

Dependencies: Python, Tkinter, and psxavenc.

### Koudelka_MCF_Subtitle_Tool_GUI__TTF

Extracts, reviews, translates, and rebuilds subtitle graphics in Japanese MCF files.

- opens one MCF or an entire folder;
- extracts subtitle entries to CSV;
- supports search and mass replacement;
- visually marks mass-edited entries;
- identifies entries found through OCR;
- imports and exports translation CSV files;
- generates one MCF or every MCF in a folder;
- preserves IDs, triplets, and metadata;
- creates new files without modifying original MCF files.

Rendering modes:

- **Sharp CRT text:** Tahoma Regular 12, rendered directly as monochrome pixels on the final 300×39 canvas, without LANCZOS, antialiasing, gray shades, outlines, or shadows;
- **Smoothed TTF:** legacy supersampled rendering;
- **Native FT4 font:** preserves the original game appearance.

MCF files always store bitmaps. The tool renders text externally and writes indexed images in the structure expected by the game.

Dependencies: Python, Tkinter, Pillow, and NumPy. OCR additionally requires pytesseract, Tesseract OCR, and <code>jpn.traineddata</code>.

For CRT mode, select the Windows-installed Tahoma at <code>C:\Windows\Fonts\tahoma.ttf</code>. Do not redistribute Tahoma files in the repository.

### Koudelka_TX4_Tradutor_GUI

Views, translates, and rebuilds:

~~~text
\MENU\ITEMS\001.TX4
\MENU\MENUHELP.TX4
~~~

Main features:

- displays each block and its real palette;
- supports title and description OCR;
- imports and exports CSV;
- preserves original titles where required;
- uses black Arial without a shadow for item descriptions;
- limits descriptions to the left column so they do not overlap item artwork;
- automatically wraps lines;
- preserves headers, CLUTs, padding, and total file size;
- handles the nine real MENUHELP pages separately;
- rejects text that does not fit instead of silently clipping it;
- never overwrites the original TX4.

Current dependencies: Python 3.10+, Tkinter, and Pillow. Optional OCR invokes the Tesseract executable directly.

> [!NOTE]
> The old installer in this folder still mentions EasyOCR and PyTorch, but the current source code does not use them. They are not required by the current version.

### MDT Inject

Injects one MDT or a structured MDT folder into a BIN image.

- preserves relative paths;
- supports a configurable internal prefix;
- works on a copy of the BIN by default;
- can stop on the first error or continue the batch;
- writes a detailed log;
- does not modify input MDT files.

Dependencies: Python, Tkinter, MSYS2/Bash, and psxinject.

### MDT Translator

Reads, translates, validates, and rebuilds MDT files.

- opens one file or a complete folder;
- locates text blocks;
- displays capacity and used-byte counts;
- normalizes supported PT-BR characters;
- imports and exports CSV;
- filters by state or text;
- blocks entries that exceed available space;
- creates new MDT files while preserving the structure;
- does not modify original MDT files.

Translation and rebuilding require only Python and Tkinter. The injection modules in the same folder also require MSYS2/Bash and psxinject.

Main input/output path: <code>\MDT\*.MDT</code>.

### TEX Importer

Converts PNG images into TEX using an original TEX as a template.

- requires the expected PNG dimensions;
- preserves the original palette or creates a new PS1 BGR555 palette with up to 256 colors;
- preserves palette STP behavior;
- provides a special mode for splitting one 320×240 image into <code>BACK1.TEX</code> and <code>BACK2.TEX</code>;
- uses a shared palette when creating BACK1/BACK2;
- offers before/after previews and automatic reload;
- preserves headers and file size;
- creates a new TEX and a JSON report.

Dependencies: Python, Tkinter, and Pillow.

Main input/output path: <code>\DATA\*.TEX</code>.

### TEX Viewer

Views TEX files and exports them to PNG.

- opens one TEX or a complete folder;
- displays the PS1 BGR555 palette;
- offers zoom and transparency controls;
- exports one file or a batch;
- automatically combines <code>BACK1.TEX</code> and <code>BACK2.TEX</code> into a 320×240 screen;
- is read-only and never modifies TEX files.

Dependencies: Python, Tkinter, and Pillow.

### tile_molester_021

Tile Molester is an external Java utility for viewing and editing tiled graphics in binary files. It can assist with manual graphics research, but it does not automatically understand Koudelka-specific formats.

Dependency: Java. This utility has its own project and license and is not original code from this repository.

### TX8 Extractor

Extracts, previews, and replaces images in TX8 files.

- opens one TX8 or a complete folder;
- recognizes single-block and multi-block files;
- exports linear, panel, and 320×240 screen views when applicable;
- recognizes NEWF0 and MENUPAD variants;
- preserves palettes, headers, metadata, padding, and the STP bit;
- imports a PNG into a selected image;
- imports multiple numbered PNGs at once;
- provides Previous/Next preview navigation;
- combines multiple replacements into one new TX8;
- rejects incompatible dimensions, transparency, or layouts;
- does not modify source TX8 or PNG files.

Batch matching examples:

~~~text
001_tela_320x240_PTBR.png -> image 001
002_tela_320x240_PTBR.png -> image 002
005_linear.png            -> image 005
~~~

Dependencies: Python 3.10+, Tkinter, and Pillow.

Common paths: <code>\DISK\*.TX8</code> and <code>\MENU\GAMEOVER\*.TX8</code>.

## Dependencies

### Base requirements

- 64-bit Windows 10 or Windows 11;
- Python 3.10 or newer;
- pip;
- Tcl/Tk and Tkinter, normally included with the official Windows Python installer;
- a legally obtained BIN/CUE image created from a disc owned by the user.

Enable **Add Python to PATH** and keep the Tcl/Tk component selected when installing Python.

### Python packages

Create a virtual environment in the repository root:

~~~bat
py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install Pillow numpy pytesseract
~~~

Pillow is used by the TEX, TX4, TX8, Interface Menu, and MCF graphics tools. NumPy and pytesseract are required by the MCF subtitle tool.

### External programs

| Dependency | Used by | Notes |
|---|---|---|
| PSXImager/psxrip | BIN Extractor | Must be built with the disc mode 16 modification |
| PSXImager/psxinject | Inject files and MDT Inject | Replaces files inside a BIN |
| MSYS2/Bash | Injectors | Required by the current injection scripts |
| FFmpeg and ffprobe | AVI to STR | Video/audio normalization and analysis |
| psxavenc | AVI to STR and MCF Audio Injector | MDEC, XA, and SPU-ADPCM encoding |
| Java 8+ | jPSXdec and Tile Molester | Java runtime |
| jPSXdec 2.1 | AVI to STR and MCF Audio Extractor | STR analysis and XA conversion |
| Tesseract OCR | MCF Subtitle Tool and TX4 | Local OCR |
| <code>jpn.traineddata</code> | Japanese MCF OCR | Must be installed in Tesseract's tessdata folder |
| Arial | TX4 | Normally located at <code>C:\Windows\Fonts\arial.ttf</code> |
| Tahoma Regular | MCF CRT | Normally located at <code>C:\Windows\Fonts\tahoma.ttf</code> |

After installation, FFmpeg, ffprobe, Java, and Tesseract may be added to PATH or selected manually in interfaces that expose the corresponding field.

## psxrip disc mode 16 modification

For the tested Japanese image, libcdio reports numeric disc mode 16. The original psxrip stops because that value is not part of its recognized disc-mode list.

The modification changes only this validation. Instead of throwing an exception, the program prints a warning and continues:

~~~text
++ WARN: Unknown disc mode 16; continuing anyway
~~~

Replacement applied to <code>src/psxrip.cpp</code>:

~~~cpp
switch (discMode) {
    case CDIO_DISC_MODE_CD_DATA:
    case CDIO_DISC_MODE_CD_XA:
    case CDIO_DISC_MODE_CD_MIXED:
        break;

    default:
        cdio_warn("Unknown disc mode %d; continuing anyway", discMode);
        break;
}
~~~

All later checks remain enabled. psxrip still verifies the first track, its data/XA format, and the presence of an ISO 9660 filesystem. The warning therefore does not make arbitrary input files valid disc images.

The <code>BIN Extrator\psxrip_modo16.cpp</code> file may be kept as a reference for the modification. For GPL redistribution, it is not a replacement for the complete corresponding PSXImager source.

### Building with MSYS2/MinGW64

Install MSYS2 and run the following from an **MSYS2 MinGW x64** terminal:

~~~bash
pacman -S --needed git make autoconf-wrapper automake-wrapper \
  mingw-w64-x86_64-gcc mingw-w64-x86_64-pkgconf \
  mingw-w64-x86_64-libcdio mingw-w64-x86_64-vcdimager
~~~

Then:

~~~bash
git clone https://github.com/cebix/psximager.git
cd psximager
./bootstrap
./configure
make
~~~

Apply the modification above before running <code>make</code>. Place the resulting <code>src/psxrip.exe</code> beside <code>bin_extrator_gui.py</code>. The generated <code>src/psxinject.exe</code> can be selected in the injector interfaces.

Because this repository does not publish compiled releases, every user must build these external tools or obtain them from their respective projects in accordance with their licenses.

## Running the tools

Activate the virtual environment and run the main script for the desired tool. The existing BAT launchers may also be used when Python is available through PATH.

Examples:

~~~bat
python "BIN Extrator\bin_extrator_gui.py"
python "AVI to STR\koudelka_avi_to_str_gui.py"
python "Inject files\koudelka_inject_arquivo_gui.py"
python "Interface Menu (bins)\koudelka_interface_gui.py"
python "Koudelka_MCF_Audio_Extractor_GUI\koudelka_mcf_audio_extractor_gui.py"
python "Koudelka_MCF_Audio_Injector_GUI\koudelka_mcf_audio_injector_gui.py"
python "Koudelka_MCF_Subtitle_Tool_GUI__TTF\koudelka_legendas_gui_v6.py"
python "Koudelka_TX4_Tradutor_GUI\koudelka_tx4_tradutor_gui.py"
python "MDT Inject\koudelka_inject_mdt_mass_v3_msys2.py"
python "MDT Tradutor\koudelka_mdt_gui.py"
python "TEX Importer\koudelka_png_to_tex_gui.py"
python "TEX Viewer\koudelka_tex_viewer_gui.py"
python "TX8 Extrator\koudelka_tx8_gui.py"
java -jar "jpsxdec_v2.1-beta\jpsxdec.jar"
java -jar "tile_molester_021\tilemolester.jar"
~~~

## Recommended workflow

1. Back up the BIN/CUE image.
2. Extract the disc with BIN Extractor and keep LBN preservation enabled.
3. Edit or rebuild files with the corresponding tool.
4. Always save to a new file or output folder.
5. Inject generated files into a copy of the BIN.
6. Test the resulting image in an emulator before writing physical media or replacing any backup.

## Files that must not be uploaded to GitHub

- <code>.BIN</code>, <code>.CUE</code>, <code>.ISO</code>, or BIOS images;
- original files extracted from the game;
- MCF, MDT, STR, TX4, TX8, TEX, FT4, or other game-owned assets;
- <code>tahoma.ttf</code> and <code>tahomabd.ttf</code>;
- third-party executables and JARs in a repository declared as source-only;
- logs, caches, reports, and settings containing personal paths;
- backup folders and generated output.

Starter <code>.gitignore</code>:

~~~gitignore
__pycache__/
*.py[cod]
.venv/
*.log
*_settings.json
backup_*/
*.BIN
*.bin
*.CUE
*.cue
*.ISO
*.iso
*.MCF
*.mcf
*.MDT
*.mdt
*.STR
*.str
*.TX4
*.tx4
*.TX8
*.tx8
*.TEX
*.tex
*.FT4
*.ft4
*.ttf
*.otf
*.exe
*.jar
~~~

If tests need fixture files, use only synthetic samples created for testing that do not contain game data.

## Licensing and redistribution

The repository owner must add a license for the original Python code. If the repository contains modified PSXImager source, a simple approach is to license the compatible collection under GPL-2.0-or-later while preserving the individual notices for separate external components.

- [PSXImager](https://github.com/cebix/psximager) — GPL-2.0-or-later. A modified distribution must preserve its license and provide the complete corresponding source code.
- [psxavenc](https://github.com/WonderfulToolchain/psxavenc) — zlib license.
- [FFmpeg](https://ffmpeg.org/legal.html) — LGPL or GPL depending on build configuration.
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — Apache-2.0.
- [jPSXdec](https://github.com/m35/jpsxdec/blob/readme/jpsxdec/doc/LICENSE.txt) — custom non-commercial license.
- Pillow, NumPy, and pytesseract retain their respective licenses and notices when redistributed.
- Tahoma font files supplied with Windows must not be copied into the repository. See the [Microsoft font redistribution FAQ](https://learn.microsoft.com/en-us/typography/fonts/font-faq).

Maintain a <code>THIRD_PARTY_NOTICES.md</code> file listing the project, version, link, and license for every external dependency.

## Disclaimer

This is an independent research, translation, and modding project. It is not affiliated with or endorsed by the Koudelka, Sacnoth, SNK, or distributor rights holders. Use only files extracted from a game copy that you own and comply with the laws applicable in your region.
