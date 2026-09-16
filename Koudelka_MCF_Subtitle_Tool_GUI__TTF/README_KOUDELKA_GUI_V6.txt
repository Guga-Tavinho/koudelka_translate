KOUDELKA MCF SUBTITLE TOOL v6 - TRADUÇÃO EM MASSA

MODO CRT NÍTIDO / TTF / FT4
===========================

A ferramenta possui três modos de renderização:

- Texto CRT nítido (recomendado): modo padrão. Usa Tahoma Regular 12 e
  rasteriza a frase inteira diretamente na grade final de 300x39 pixels.
  O desenho é monocromático desde a origem: não há antialiasing, LANCZOS,
  tons de cinza, contorno, halo ou sombra. O resultado usa somente fundo
  transparente e branco opaco, com centralização normal.
- TTF suavizado (legado): mantém o antigo método com superamostragem 4x,
  LANCZOS e limiar. Fica disponível para comparar projetos anteriores.
- Fonte nativa FT4: mantém o visual original do jogo.

O arquivo tahoma.ttf (Tahoma Regular) fica junto ao programa e é carregado
automaticamente. O tahomabd.ttf permanece disponível para o modo legado.
Outra fonte .ttf ou .otf pode ser escolhida na interface. O tamanho
recomendado para o modo CRT nítido é 12. Valores aceitos: 8 a 16, desde que
a fonte escolhida caiba verticalmente nos 15 pixels reservados pelo MCF.

O MCF sempre armazena bitmaps; diferentemente do MDT, ele não contém códigos
de texto para o jogo desenhar em tempo real. O modo CRT nítido reproduz o
resultado visual mais próximo possível dentro do formato original, sem
alterar a estrutura que o jogo espera.

NOVO FLUXO
==========

A v6 adiciona importação/exportação para tradução em massa.

Fluxo recomendado:

1. MCF japonês
2. Extrair MCF -> CSV
3. Exportar para tradução
4. Traduzir a coluna portugues inteira
5. Importar traduções
6. Validar todas
7. Gerar MCF


PESQUISA E SUBSTITUIÇÃO EM MASSA
================================

O campo Pesquisar filtra instantaneamente a tabela por ID, triplet,
texto japonês ou texto em português. Use Próximo para navegar pelos
resultados e Limpar para voltar a exibir todas as legendas.

Para substituir uma palavra em todas as traduções:

1. Digite o texto original em Pesquisar.
2. Digite o novo texto em Substituir por.
3. Escolha Palavra inteira e Diferenciar maiúsculas conforme necessário.
4. Clique em Substituir todos no português e confirme.

Cada legenda modificada recebe um ✓ e fundo amarelo. A marca também é
salva no CSV na coluna alterado_em_massa, para continuar visível depois
que o arquivo for fechado e carregado novamente.


MODO PASTA MCF
==============

Clique em Abrir pasta MCF para carregar recursivamente todos os arquivos
.MCF de uma pasta. A ferramenta procura primeiro um CSV correspondente
para cada arquivo. Quando não encontra, analisa o MCF diretamente usando
o FONTS.FT4; se houver um FONTS.FT4 dentro da pasta, ele é localizado e
carregado automaticamente.

Na tabela, cada MCF aparece como um grupo azul:

    ☐ SC01_0.MCF (quantidade)
    ☑ SC02_0.MCF (quantidade)

Clique em ☐/☑ ou no controle da árvore para ampliar ou recolher todas as
legendas daquele MCF. Uma pesquisa abre automaticamente somente os grupos
que possuem resultados.

Quando o OCR encontra texto, a legenda recebe ✓ na coluna OCR. O grupo do
MCF fica amarelo e mostra "⚠ OCR: quantidade". Marque o checkbox OCR
encontrados, na área de pesquisa, para exibir somente essas legendas e os
MCFs que possuem resultados de OCR. O status e o ocr_score continuam sendo
salvos nos CSVs.

No modo pasta, o botão muda para GERAR TODOS OS MCFs. Ele valida primeiro
todas as traduções e cria automaticamente:

    pasta selecionada\MCF_TRADUZIDOS

Dentro dela são gravados todos os MCFs traduzidos e um CSV de mesmo nome
para cada MCF. A estrutura relativa das subpastas é preservada para evitar
que arquivos de nomes iguais sejam sobrescritos. Cada CSV novo aponta para
seu MCF traduzido e pode ser aberto depois para futuras edições.

Ao salvar um projeto aberto por pasta, o CSV combinado recebe as colunas
arquivo_mcf e caminho_mcf. Elas preservam os grupos quando o CSV é aberto
novamente e tornam a importação de traduções segura mesmo quando arquivos
diferentes possuem IDs iguais.


EXPORTAR PARA TRADUÇÃO
======================

Clique:

    Exportar para tradução

O programa gera:

id;triplet_inicio;triplet_fim;original_jp;portugues

Você pode abrir esse CSV em outro programa ou enviar para uma ferramenta
de tradução em massa.

IMPORTANTE:
- traduza somente a coluna portugues;
- não altere id;
- não altere triplet_inicio;
- não altere triplet_fim.


IMPORTAR TRADUÇÕES
==================

Depois clique:

    Importar traduções

A ferramenta procura automaticamente a coluna de português. São aceitos
nomes como:

portugues
Português
ptbr
pt_br
traducao
tradução
translation

A associação é feita nesta ordem:

1. ID
2. triplet_inicio + triplet_fim
3. ordem das linhas, somente se não houver chaves e você confirmar

Somente o campo portugues é substituído.

São preservados:
- triplet_inicio
- triplet_fim
- original_jp
- imagem
- status
- demais metadados


EXEMPLO
=======

ANTES:

id;triplet_inicio;triplet_fim;original_jp;portugues
43;711;726;"ありがとうオグデンさん|恩にきますよ";

DEPOIS DE TRADUZIR EM MASSA:

id;triplet_inicio;triplet_fim;original_jp;portugues
43;711;726;"ありがとうオグデンさん|恩にきますよ";"Obrigado, Ogden. Fico lhe devendo."

Depois basta importar esse arquivo e gerar o MCF.


OCR
===

A v6 mantém o OCR japonês e o progresso em segundo plano da v5.

Tesseract:
C:\Program Files\Tesseract-OCR\tesseract.exe

Idioma:
C:\Program Files\Tesseract-OCR\tessdata\jpn.traineddata
