[![Visitas](https://hits.sh/github.com/Guga-Tavinho/koudelka_translate.svg?style=flat-square&label=visitas&color=blue)](https://hits.sh/github.com/Guga-Tavinho/koudelka_translate/)
# Koudelka PS1 Translation and Modding Tools

[English](README.en.md)

Este repositório contém ferramentas em código-fonte criadas para inspecionar, traduzir, reconstruir e injetar recursos usados na versão de PlayStation de **Koudelka**.

> [!IMPORTANT]
> Este é um projeto distribuído apenas em código-fonte. Ele não fornece imagem do jogo, arquivos originais, BIOS, versões compiladas ou recursos protegidos por direitos autorais.

## 🎥 Demonstração da tradução

[![Assista ao vídeo da tradução de Koudelka](www.github.com/Guga-Tavinho/koudelka_translate/blob/main/exec-fd9ce22d-03b0-4e47-9d9d-8378b9d120de.png)](https://youtu.be/drU19__VhAE)

---

## Informações importantes sobre as versões do jogo

1. A versão americana não contém legendas nas CGIs/cutscenes renderizadas em tempo real armazenadas em MCF.
2. Apenas a versão japonesa possui essas legendas.
3. Por isso, a ferramenta de legendas MCF deve usar os MCFs japoneses como base. O MCF armazena as legendas como imagens indexadas, não como texto comum.

As ferramentas foram desenvolvidas e testadas principalmente no Windows 10/11 de 64 bits.

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

Link: https://github.com/m35/jpsxdec
jPSXdec é uma ferramenta externa para analisar e converter mídia de PlayStation 1. Neste projeto ela é usada principalmente para:

- analisar STRs;
- conferir a quantidade de quadros;
- extrair ou converter áudio CD-ROM XA de determinados MCFs.

Dependência: Java 8 ou superior.

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

Para o modo CRT, selecione a Tahoma instalada pelo Windows em <code>C:\Windows\Fonts\tahoma.ttf</code>.

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
Link: https://github.com/toruzz/TileMolester

Dependência: Java.

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
- [Python 3.10 ou superior](https://www.python.org/downloads/windows/);
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
| [PSXImager](https://github.com/cebix/psximager)/psxrip | BIN Extrator | Deve ser compilado com a modificação do modo 16 |
| [PSXImager](https://github.com/cebix/psximager)/psxinject | Inject files e MDT Inject | Substitui arquivos dentro da BIN |
| [MSYS2](https://www.msys2.org/)/Bash | Injetores | Necessário pelo fluxo atual dos scripts de injeção |
| [FFmpeg e ffprobe](https://ffmpeg.org/download.html) | AVI to STR | Normalização e análise de vídeo/áudio |
| [psxavenc](https://github.com/WonderfulToolchain/psxavenc) | AVI to STR e MCF Audio Injector | Codificação MDEC, XA e SPU-ADPCM |
| [Java 8+](https://adoptium.net/) | jPSXdec e Tile Molester | Runtime Java |
| [jPSXdec 2.1](https://github.com/m35/jpsxdec/releases) | AVI to STR e MCF Audio Extractor | Análise de STR e conversão XA |
| [Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html) | MCF Subtitle Tool e TX4 | OCR local |
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

O arquivo <code>BIN Extrator\psxrip_modo16.cpp</code> contém uma cópia de referência dessa alteração.

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

Como não são fornecidas versões compiladas, compile essas ferramentas externas ou obtenha-as nos respectivos projetos oficiais.

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

## Aviso

Este projeto é uma ferramenta independente de pesquisa, tradução e modificação. Ele não é afiliado nem endossado pelos detentores dos direitos de Koudelka, Sacnoth, SNK ou seus distribuidores. Use somente arquivos obtidos de uma cópia do jogo que você possui e respeite a legislação aplicável em sua região.
