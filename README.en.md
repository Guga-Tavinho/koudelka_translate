# Koudelka PS1 Translation and Modding Tools

[Português (Brasil)](README.md)

This repository contains source-code tools created to inspect, translate, rebuild, and inject resources used by the PlayStation version of **Koudelka**.

> [!IMPORTANT]
> This is a source-only project. It does not provide a game image, original game files, BIOS files, compiled releases, or copyrighted assets.

---

## Important information about game versions

1. The US version does not contain subtitles for real-time rendered CGI/cutscene sequences stored in MCF files.
2. Only the Japanese version contains these subtitles.
3. Therefore, the MCF subtitle tool must use Japanese MCF files as its base. MCF subtitles are stored as indexed images, not as ordinary text strings.

The tools were developed and tested primarily on 64-bit Windows 10/11.

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
Link: https://github.com/m35/jpsxdec

jPSXdec is an external PlayStation 1 media analysis and conversion utility. This project uses it mainly to:

- analyze STR files;
- verify frame counts;
- extract or convert CD-ROM XA audio from some MCF files.

Dependency: Java 8 or newer.

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

For CRT mode, select the Windows-installed Tahoma at <code>C:\Windows\Fonts\tahoma.ttf</code>.

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
Link: https://github.com/toruzz/TileMolester
Dependency: Java.

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
- [Python 3.10 or newer](https://www.python.org/downloads/windows/);
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
| [PSXImager](https://github.com/cebix/psximager)/psxrip | BIN Extractor | Must be built with the disc mode 16 modification |
| [PSXImager](https://github.com/cebix/psximager)/psxinject | Inject files and MDT Inject | Replaces files inside a BIN |
| [MSYS2](https://www.msys2.org/)/Bash | Injectors | Required by the current injection scripts |
| [FFmpeg and ffprobe](https://ffmpeg.org/download.html) | AVI to STR | Video/audio normalization and analysis |
| [psxavenc](https://github.com/WonderfulToolchain/psxavenc) | AVI to STR and MCF Audio Injector | MDEC, XA, and SPU-ADPCM encoding |
| [Java 8+](https://adoptium.net/) | jPSXdec and Tile Molester | Java runtime |
| [jPSXdec 2.1](https://github.com/m35/jpsxdec/releases) | AVI to STR and MCF Audio Extractor | STR analysis and XA conversion |
| [Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html) | MCF Subtitle Tool and TX4 | Local OCR |
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

The <code>BIN Extrator\psxrip_modo16.cpp</code> file contains a reference copy of this modification.

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

Because compiled releases are not provided, build these external tools or obtain them from their official projects.

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

## Disclaimer

This is an independent research, translation, and modding project. It is not affiliated with or endorsed by the Koudelka, Sacnoth, SNK, or distributor rights holders. Use only files extracted from a game copy that you own and comply with the laws applicable in your region.
