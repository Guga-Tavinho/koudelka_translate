#!/usr/bin/env python3
"""Consolida a tradução PT-BR do MDT do Disco 1 e gera a árvore reinserida."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from koudelka_mdt_core import (
    entry_validation,
    export_csv,
    load_folder,
    write_folder,
)


# Traduções revisadas para entradas ausentes, incompletas ou suspeitas no CSV antigo.
# A ordem é validada contra a lista de candidatos extraída da árvore original.
CURATED = [
    '''Achou "Garrafa de Sangue".''',                                      # 1
    '''Pegou "Garrafa de Sangue".''',                                      # 2
    '''A porta esta bem fechada--
nao abre.''',                                                              # 3
    '''A porta esta bem trancada
e nao pode ser aberta.
Parece que Edward e James
foram para a biblioteca.''',                                               # 4
    '''  Cemiterio''',                                                      # 5
    '''...Voce sente alguem
atras de voce--
uma presenca conhecida.''',                                                # 6
    '''Ha uma sepultura velha e gasta.''',                                 # 7
    '''Nao pode tirar nada do tanque
sem um recipiente vazio
para guardar o liquido.''',                                                 # 8
    '''Obteve "Garrafa de Acido".''',                                      # 9
    '''A porta foi destruida;
nao pode ser aberta.''',                                                    # 10
    '''Ha uma cavidade que
parece ter sido feita por agua.''',                                         # 11
    '''Quer usar
"Garrafa de Sangue"?''',                                                    # 12
    '''O cheiro de sangue do frasco
envolve a estatua,
que comeca a tremer!''',                                                    # 13
    ''' 
 
E uma criatura.
Diz: "O cemiterio...
O tumulo de Sao Daniel...
E o tumulo da menina..."''',                                                # 14
    ''' 
 
E uma criatura.
Diz: "Aquela mulher...
Escreveu cartas para criancas...
Mas nunca as entregou..."''',                                               # 15
    ''' 
 
E uma criatura.
Diz: "Precisa parar...
A estrela que Charlotte deixa
para tras... Ou o brilho..."''',                                            # 16
    '''E uma criatura.
Diz: "Orgao...
Mova... Va para baixo..."''',                                               # 17
    ''' 
 
E uma criatura.
Diz: "Se quer acido...
Pegue um frasco vazio...
Laboratorio de Patrick..."''',                                              # 18
    '''E uma criatura.
Diz: "Patrick... Como pode
fazer isso comigo?"''',                                                     # 19
    ''' 
 
E uma criatura.
Diz: "So podem ser vistos
no escuro... Portas ocultas...
Livros ocultos..."''',                                                      # 20
    '''E uma criatura.
Diz: "Braco de Daniel...
Forca sagrada..."''',                                                       # 21
    '''E uma criatura.
Diz: "O par de bonecas...
A mulher vira as costas para ele..."''',                                    # 22
    '''E uma criatura.
Diz: "Onde esta o pingente
que voce deixou cair?"''',                                                  # 23
    '''E uma criatura.
Diz: "Se for... quarto andar...
Oculto... sagrado..."''',                                                   # 24
    '''E uma criatura.
Diz: "Eu so trabalhava aqui...
Patrick... me contratou..."''',                                             # 25
    '''E uma criatura.
Diz: "Logo... Voce os encontrara
em breve..."''',                                                           # 26
    '''E uma criatura.
Diz: "Vigna e Valna...
So querem suas bonecas..."''',                                              # 27
    '''E uma criatura.
Diz: "Se tiver o diario de pesquisa...
O Documento Emigre... Roger..."''',                                        # 28
    ''' 
 
E uma criatura.
Diz: "Se tocar o disco...
O ultimo experimento
de Patrick..."''',                                                          # 29
    '''A igreja foi
tomada pelas chamas.
Nao da para entrar.''',                                                      # 30
    '''Uma inquietacao toma conta de voce
ao notar que ja nao esta
com o pingente.''',                                                         # 31
    '''Ao entrar mais fundo
no jardim de ervas,
uma planta gigante ataca!
 ''',                                                                       # 32
    '''Com o monstro derrotado,
a fonte voltou a se encher
de agua benta.
 
 
(Pode salvar aqui.)''',                                                     # 33
    '''Ha um homem caido no chao.
Parece estar desacordado.''',                                               # 34
    '''Obteve "Escopeta 6".''',                                             # 35
    '''Achou "Escopeta 6".''',                                              # 36
    '''Voce encontra um deposito
cheio de itens no fim do tunel.''',                                         # 37
    '''  Deposito Subterraneo''',                                           # 38
    '''Parece haver algo escrito
sob a chama da vela...''',                                                  # 39
    '''Oito simbolos foram
escritos na caixa.
Alguns sao vermelhos,
os outros, azuis.''',                                                       # 40
    '''O reboco esta cedendo--
parece haver agua
escorrendo pela parede.
 
Achou uma "Estatua de Bode"
dentro da parede.''',                                                       # 41
    '''Parece haver uma estatua
sob o reboco da parede.
Se derramasse agua por cima,
talvez pudesse retira-la.''',                                                # 42
    '''Ha 4 marcas alinhadas.''',                                           # 43
    '''Parece que a agua
esta subindo de baixo.''',                                                   # 44
    '''  Deposito''',                                                       # 45
    '''Ao subir as escadas,
voce encontra um homem armado.
Sem dizer uma palavra,
ele comeca a atirar!''',                                                     # 46
    '''A porta nao abre--
parece usar algum tipo
de mecanismo secreto.''',                                                   # 47
    '''O que significa o desenho no chao?''',                               # 48
    '''Esta marca parece a que estava
na caixa do porao...''',                                                    # 49
    '''E igual ao que estava escrito
no pilar do primeiro andar.''',                                             # 50
    '''  Deposito, 2o Andar''',                                             # 51
    '''Elaine alcancou voce!''',                                            # 52
    '''  Igreja, 5o Andar''',                                               # 53
    '''As chamas sobem--
nao pode descer.''',                                                        # 54
    '''Se jogar "Braco de Daniel"
e invocar o poder do fogo...''',                                            # 55
    '''  Igreja, Caldeirao da Vida, Subsolo''',                             # 56
    ''' 
Voce ve um orgao com runas
entalhadas nas teclas.
 
Apenas quatro teclas
podem ser pressionadas;
as runas nelas dizem:
Pessoas, Segredo, Dor
e Luz.''',                                                                  # 57
    '''O orgao ressoa
com uma nota reverberante!''',                                              # 58
    '''Nada acontece--
as teclas nao foram pressionadas
na ordem certa.''',                                                         # 59
    '''  Igreja, Santuario, 1o Andar''',                                    # 60
    ''' 
 
A Arvore da Vida parou.
Atraves do vitral,
voce ve um penhasco
erguendo-se do oceano.''',                                                   # 61
    '''Ha marcas sob o caixao;
ele deve ter sido arrastado.''',                                            # 62
    '''QUWQ''',                                                             # 63
    '''QUQU''',                                                             # 64
    '''Ha uma gargula la dentro--
talvez voces tres, juntos,
consigam derrota-la.''',                                                     # 65
    '''Ha uma gargula la dentro--
nao pode ir sozinho.''',                                                    # 66
    '''Ha uma gargula la dentro--
ainda quer entrar?''',                                                      # 67
    '''  Patio Interno, Porta da Igreja''',                                 # 68
    '''  Patio Interno, Arbor''',                                           # 69
    '''Foi trancada pelo outro lado
e nao abre por aqui.''',                                                     # 70
    '''  Patio, Aposentos de Patrick''',                                    # 71
    '''Por mais que tente, nao consegue tirar
"Sacnoth" da estatua--
algo o prende no lugar.''',                                                  # 72
    '''  Patio Interno, Portao''',                                          # 73
    ''' 
Este e o portao do mosteiro.
Infelizmente,
esta trancado e nao pode ser aberto.''',                                    # 74
    '''  Aposentos do Zelador, 2o Andar''',                                 # 75
    '''!Dfv(''',                                                            # 76
    '''  Quarto de Patrick, 1o Andar''',                                    # 77
    '''Em "Patrick's Memo" estava escrito "70kg".
Talvez deva ajustar o
contrapeso para esse peso.''',                                              # 78
    '''O contrapeso esta
ajustado para 25kg.''',                                                     # 79
    ''' 
Ha uma balanca
com um contrapeso.
Ajustando o contrapeso,
e possivel alterar o equilibrio
da balanca.''',                                                             # 80
    '''Ha uma abertura sob
a lareira, com uma
escada que leva ao subsolo.''',                                             # 81
    '''Voce ve uma balanca.
Ao subir nela, marca 46kg.
Parece que voce engordou.''',                                               # 82
    '''Voce ve uma balanca.
Ao subir nela, marca 45kg.''',                                              # 83
    '''Parece que pode mover
a estatua se tentar.''',                                                    # 84
    '''Parece que Roger
ainda esta pesquisando.''',                                                 # 85
    ''' 
 
Voce sente a planta pulsar.
Antes constante,
o pulso acelera de repente,
como se a planta fosse explodir.''',                                        # 86
    '''  Igreja, 4o Andar''',                                               # 87
    '''  Sacristia, Piso 1''',                                              # 88
    '''Parece haver algo
nas sombras,
mas nao da para ver bem.
 
 
Talvez acendendo uma vela...''',                                            # 89
    ''' 
A sala se ilumina
quando voce acende a vela.
Foi usado o ultimo fosforo;
voce joga fora a
"Fosforeira" vazia.''',                                                     # 90
    '''A parede desabou;
nao da para seguir.''',                                                     # 91
    '''Ha algo se movendo atras de voce...''',                              # 92
    '''Obteve "Escopeta 2".''',                                             # 93
    '''Achou "Escopeta 2".''',                                              # 94
    '''Ao tentar prosseguir,
uma gargula ataca de repente!''',                                           # 95
    '''  Igreja, Nave, 1o Andar''',                                         # 96
    '''Voce ve a sala interna
por uma fenda na parede--
parece ser uma igreja.
 
Porem, uma planta estranha
impede a passagem.''',                                                       # 97
    '''Parece possivel descer
se tiver algum tipo de escada.''',                                          # 98
    '''  Masmorra, 2o Andar''',                                             # 99
    '''Esta trancado com
um cadeado de 4 digitos.''',                                                 # 100
    '''O cadeado abriu!''',                                                 # 101
    '''Nada aconteceu--
tente outra
combinacao.''',                                                             # 102
    '''Ha uma mumia
com vestido de noiva
dentro do armario.
Quando voce a observa,
ela abre os olhos
e ataca de repente!''',                                                     # 103
    '''Ha um vestido muito antigo
la dentro.
Parece ter sido popular
ha 30 anos.''',                                                             # 104
    '''Ha um vitral mostrando
um martir queimado
na fogueira.
 
Ha uma escrita vermelha
na parte inferior,
 
mas as outras cores
a tornam ilegivel.
Talvez, esfregando algo vermelho,
seja possivel ler as letras.''',                                            # 105
    ''' 
Os numeros "7038"
aparecem escritos em grego.
 
 
Ao ve-los, voce se lembra
do bau no segundo andar,
que tinha um cadeado
de 4 digitos.''',                                                           # 106
    '''  Masmorra, 1o Andar''',                                             # 107
    ''' 
 
Voce ouve uma garota rindo baixo.
De repente,
os moveis da sala vibram
e o proprio espaco se distorce.''',                                         # 108
    '''  Cela de Charlotte, 1o Andar''',                                    # 109
    ''' 
Voce ve algo verde e brilhante
entre os dois corpos.
Parece ser a "Chave Verde",
mas nao pode alcanca-la--
Valna e Vigna bloqueiam o caminho.''',                                      # 110
    ''' 
Ao tentar pegar a chave,
as mumias comecam a falar.
Valna diz: "Devolva nossas bonecas",
e Vigna:
"Corra! Fuja enquanto pode!"''',                                            # 111
    '''Vigna e Valna parecem mortas,
de novo...''',                                                             # 112
    '''Ha placas com nomes
presas as mumias;
nelas se le "Valna" e "Vigna".''',                                          # 113
    '''  Biblioteca, Piso 2''',                                             # 114
    '''Parece que ja houve
uma porta aqui,
mas ela desapareceu.
 
Tera de procurar
outra porta em outro lugar.''',                                             # 115
    '''Voce alinhou as letras gregas
como as do mural
de vitral.''',                                                              # 116
    '''Parece que abriria
se as 5 letras gregas
fossem alinhadas corretamente...
 
Mas dificilmente sera possivel
abrir apenas por tentativa.''',                                             # 117
    '''Ao alinhar as
cinco letras gregas, o cadeado abre.''',                                    # 118
    ''' 
Voce encontra cartas
e uma caixa vermelha.
Na caixa esta escrito "Feliz Aniversario",
e dentro ha um buque de flores secas
que se desfazem ao toque.
 
Todas as cartas sao assinadas
por "Sophia D'Lota".''',                                                     # 119
    ''' 
Voce pisa seguindo
a melodia da "Caixa Musical".
Ela para de tocar
e parece quebrada.
Voce joga fora a "Caixa Musical".''',                                       # 120
    '''Ao inserir a "Peca de Relevo",
o relevo comeca a se mover.''',                                             # 121
    '''Parece que a prensa
ainda pode ser usada.''',                                                   # 122
    '''Ao ligar a prensa
apos inserir a "Tabua de Pedra",
uma forte vibracao
 
derruba a parede atras dela.
A prensa imprime o "Mapa Original",
o mapa do antigo mosteiro
gravado na "Tabua de Pedra".''',                                            # 123
    '''Parece que a prensa
esta quebrada e nao funciona.''',                                           # 124
    '''A parede aqui parece
mais fraca que as outras
e soa oca quando golpeada.
 
 
Talvez haja algo atras dela?''',                                            # 125
    '''Ha um buraco do tamanho
exato para uma pequena estatua.''',                                         # 126
    '''Ao inserir a terceira estatua,
o cadeado abre.''',                                                         # 127
    '''Ha algo nessa estante
que chama sua atencao...''',                                                # 128
    '''Uma planta estranha cresce
nas fendas da estante.
Voce sente nela um pulso fraco...''',                                       # 129
    '''  Biblioteca, Piso 1''',                                             # 130
    '''  Galeria Triangular''',                                             # 131
    '''Uma forca misteriosa
mantem a porta fechada.
Ao tentar abri-la,
um monstro ataca!''',                                                       # 132
    '''  Corredor, 2o Andar''',                                             # 133
    '''A parede desabou--
nao da para seguir.''',                                                     # 134
    '''  Nave Esquerda, 1o Andar''',                                        # 135
    '''Ao inserir o ultimo vidro,
a porta da proxima sala
e destrancada.''',                                                          # 136
    '''Igreja, Nave Esquerda, Sala do Vitral''',                            # 137
]


FINAL_OVERRIDES = {
    "It's bolted.": "Emperrada.",
    "It's locked.": "Trancada.",
    "You already pressed that key.": "Essa tecla ja foi usada.",
    "You see various items stacked\neverywhere.": (
        "Ha varios itens empilhados\npor ai."
    ),
    "It sounds hollow when you hit it.\nThere must be a hidden\ndoor in this wall.": (
        "Soa oco ao bater.\nDeve haver uma\nporta oculta nesta parede."
    ),
    "You see four dolls facing\neach other. It looks like they\ncan be moved.": (
        "Ha quatro bonecas frente a frente.\nParece que podem ser movidas."
    ),
    "You see six dolls.\nIt looks like the lower\nfour dolls can be moved.": (
        "Ha seis bonecas.\nParece que as quatro de baixo\npodem ser movidas."
    ),
    "All the paintings have been painted\nin what looks like blood.": (
        "Todas as pinturas parecem\nter sido feitas com sangue."
    ),
    "It's rusted shut.": "Esta enferrujada.",
    'Do you want to set the "Stone Tablet"\nin the printing press?': (
        'Quer por a "Tabua de Pedra"\nna prensa?'
    ),
    'You won\'t need the "Red Key" anymore.\nYou throw away the "Red Key".': (
        'A "Chave Vermelha" nao e mais util.\nVoce a joga fora.'
    ),
    'You found a hidden drawer.\nInside it is a book titled\n"Research Notes".': (
        'Achou uma gaveta secreta.\nDentro ha o livro\n"Notas de Pesquisa".'
    ),
    'The "Music Box" suddenly\nstarts playing by itself.': (
        'A "Caixa Musical" comeca\na tocar sozinha.'
    ),
}


# Nomes exibidos entre aspas. Os termos que são nomes próprios do universo
# (Sacnoth, Hestia e Listel) permanecem inalterados.
ITEM_GLOSSARY = {
    "Pistol Rounds": "Balas de Pistola",
    "Rifle Rounds": "Balas de Rifle",
    "Shotgun Shells": "Cartuchos",
    "Roman Nuts": "Nozes Romanas",
    "Red Glass Part": "Vidro Vermelho",
    "Icon's Crown": "Coroa do Icone",
    "Blue Key": "Chave Azul",
    "High Listel": "Listel Maior",
    "Rope Ladder": "Escada de Corda",
    "Red Key": "Chave Vermelha",
    "Bowgun Arrow": "Flecha de Besta",
    "Charlotte's Grave": "Tumulo de Charlotte",
    "St. Daniel's Grave": "Tumulo de Sao Daniel",
    "Daniel's Arm": "Braco de Daniel",
    "High Potion": "Pocao Maior",
    "Icon's Ring": "Anel do Icone",
    "Icon's Necklace": "Colar do Icone",
    "Pendant": "Pingente",
    "Panacea": "Panaceia",
    "Green Key": "Chave Verde",
    "Ochre Glass Part": "Vidro Ocre",
    "Vigna's Doll": "Boneca de Vigna",
    "Dragon Statue": "Estatua de Dragao",
    "Knife": "Faca",
    "Cheese": "Queijo",
    "Research Notes": "Notas de Pesquisa",
    "Flare Brooch": "Broche de Chama",
    "Icon's Earring": "Brinco do Icone",
    "Dirk": "Punhal",
    "Badge": "Medalha",
    "Patrick's Memo": "Memo de Patrick",
    "Antidote": "Antidoto",
    "Green Glass Part": "Vidro Verde",
    "Music Box": "Caixa Musical",
    "Stone Tablet": "Tabua de Pedra",
    "Disk": "Disco",
    "Goat Statue": "Estatua de Bode",
    "Lion Statue": "Estatua de Leao",
    "Bread": "Pao",
    "Monastery Map": "Mapa do Mosteiro",
    "Potion": "Pocao",
    "Valna's Doll": "Boneca de Valna",
    "Mask": "Mascara",
    "Empty Bottle": "Garrafa Vazia",
    "Guard's Diary": "Diario do Guarda",
    "Dried Food": "Comida Seca",
    "Relief Piece": "Peca de Relevo",
    "Blue Glass Part": "Vidro Azul",
    "Sophia's Letter": "Carta de Sophia",
    "Tinderbox": "Fosforeira",
    "Lifedrinker": "Bebe-Vida",
    "Old Letter": "Carta Antiga",
    "DA Pistol": "Pistola DA",
    "Pipe": "Cano",
    "Hammer": "Martelo",
    "Nitroglycerin": "Nitroglicerina",
    "Whiskey": "Uisque",
    "Teddy Bear": "Urso de Pelucia",
    "Mace": "Maca",
    "Knuckles": "Soqueira",
    "Brown Glass Part": "Vidro Marrom",
    "Bowgun": "Besta",
    "Valna'sDoll": "Boneca de Valna",
    "My Dear Wife, Elaine": "Minha Querida Elaine",
}


ENGLISH_RESIDUE = re.compile(
    r"\b(the|you|your|have|has|had|with|from|into|inside|something|nothing|"
    r"still|while|cannot|can't|it|is|are|was|were|been|being|and|but|this|"
    r"that|to|of|for|away|open|weight|appears|held|place|looks|written|"
    r"below|above|behind|somewhere|only|after|before|could|would|should|"
    r"must|them|their|here|there|what|where|when|how|down|floor|door|wall|"
    r"room|church|found|got|want|says|kind|some)\b",
    re.IGNORECASE,
)


def csv_value(value: str) -> str:
    return (value or "").replace("\\n", "\n")


def load_translation_memory(csv_path: Path) -> dict[str, str]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            original = csv_value(row.get("original_text", ""))
            translation = csv_value(row.get("translation_pt", ""))
            if translation.strip():
                grouped[original][translation] += 1
    return {
        original: variants.most_common(1)[0][0]
        for original, variants in grouped.items()
    }


def build_candidates(entries, memory: dict[str, str]) -> list[str]:
    originals = dict.fromkeys(entry.original for entry in entries)
    result = []
    for original in originals:
        translation = memory.get(original, "")
        if (
            not translation
            or translation.strip() == original.strip()
            or ENGLISH_RESIDUE.search(translation)
        ):
            result.append(original)
    return result


def write_report(entries, path: Path, normalize: bool = True) -> None:
    fields = [
        "relative_path", "local_id", "offset_hex", "original_text",
        "translation_pt", "used_bytes", "max_bytes", "status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for entry in entries:
            status, used, _ = entry_validation(entry, normalize)
            writer.writerow({
                "relative_path": entry.relative_path,
                "local_id": entry.local_id,
                "offset_hex": f"0x{entry.offset:08X}",
                "original_text": entry.original.replace("\n", "\\n"),
                "translation_pt": entry.translation.replace("\n", "\\n"),
                "used_bytes": used,
                "max_bytes": entry.max_bytes,
                "status": status,
            })


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera a árvore MDT do Disco 1 traduzida para PT-BR."
    )
    parser.add_argument("source", type=Path, help="Pasta MDT original")
    parser.add_argument("legacy_csv", type=Path, help="CSV PT-BR anterior")
    parser.add_argument("output", type=Path, help="Nova pasta MDT-Traduzido")
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    legacy_csv = args.legacy_csv.resolve()
    if output.exists():
        raise SystemExit(f"A pasta de saída já existe: {output}")

    file_data, entries, file_count = load_folder(source)
    memory = load_translation_memory(legacy_csv)
    candidates = build_candidates(entries, memory)
    if len(candidates) != len(CURATED):
        raise SystemExit(
            f"A árvore produziu {len(candidates)} candidatos, mas há "
            f"{len(CURATED)} traduções revisadas. Nada foi gravado."
        )
    memory.update(dict(zip(candidates, CURATED)))
    memory.update(FINAL_OVERRIDES)

    missing = []
    for entry in entries:
        entry.translation = memory.get(entry.original, "")
        for english_name, portuguese_name in ITEM_GLOSSARY.items():
            entry.translation = entry.translation.replace(
                f'"{english_name}"', f'"{portuguese_name}"'
            )
        status, _, _ = entry_validation(entry, True)
        if status == "EXCEDE" and entry.translation.startswith('Obteve "'):
            entry.translation = entry.translation.replace("Obteve ", "Pegou ", 1)
            status, _, _ = entry_validation(entry, True)
        if status == "EXCEDE" and entry.translation.startswith('Pegou "'):
            entry.translation = entry.translation.replace("Pegou ", "Tem ", 1)
        if not entry.translation:
            missing.append(entry)
    if missing:
        raise SystemExit(f"Restaram {len(missing)} textos sem tradução.")

    errors = []
    for entry in entries:
        status, used, detail = entry_validation(entry, True)
        if status != "OK":
            errors.append(
                f"{entry.relative_path} ID {entry.local_id}: "
                f"{used}/{entry.max_bytes} bytes - {detail}\n"
                f"  EN: {entry.original!r}\n"
                f"  PT: {entry.translation!r}"
            )
    if errors:
        print("\n".join(errors))
        raise SystemExit(f"Há {len(errors)} traduções inválidas. Nada foi gravado.")

    changed = write_folder(source, output, file_data, entries, True)
    master_csv = output / "koudelka_mdt_traducoes_PTBR.csv"
    report_csv = output / "relatorio_validacao_mdt.csv"
    export_csv(entries, master_csv, True)
    write_report(entries, report_csv, True)

    output_files = {
        path.relative_to(output).as_posix(): path
        for path in output.rglob("*")
        if path.is_file() and path.suffix.lower() == ".mdt"
    }
    mismatched = []
    for source_file, source_bytes in file_data.items():
        relative = source_file.relative_to(source).as_posix()
        target = output_files.get(relative)
        if target is None or target.stat().st_size != len(source_bytes):
            mismatched.append(relative)
    if len(output_files) != file_count or mismatched:
        raise SystemExit(
            f"Falha na verificação final: {len(output_files)}/{file_count} arquivos, "
            f"{len(mismatched)} tamanhos/caminhos inválidos."
        )

    print(f"Arquivos MDT: {file_count}")
    print(f"Textos traduzidos: {changed}")
    print("Erros de codec/tamanho: 0")
    print("Tamanhos e caminhos preservados: SIM")
    print(f"Saída: {output}")
    print(f"CSV mestre: {master_csv}")
    print(f"Relatório: {report_csv}")


if __name__ == "__main__":
    main()
