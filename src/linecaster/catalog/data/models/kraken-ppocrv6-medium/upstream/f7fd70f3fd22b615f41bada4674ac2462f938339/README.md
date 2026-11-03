---
id: https://doi.org/10.5281/zenodo.21788410
authors:
- name: Benjamin Kiessling
  affiliation: ALMAnaCH, Inria Paris
  orcid: https://orcid.org/0000-0001-9543-7827
summary: PP-OCRv6 (medium) multilingual handwritten and printed text recognition model
license: apache-2.0
software_name: kraken
software_hints:
- kraken_version>=7.1.0
language:
- ara
- cat
- ces
- chu
- cos
- dan
- deu
- dum
- eng
- fas
- fin
- fra
- frm
- gez
- gle
- grc
- heb
- hun
- ita
- kat
- lat
- lav
- lit
- mal
- mul
- nld
- nor
- oci
- ota
- pcd
- pol
- por
- ron
- rus
- slk
- slv
- spa
- srp
- swe
- syr
- ukr
- urd
- xcl
- yid
script:
- Arab
- Armn
- Cyrl
- Ethi
- Geor
- Grek
- Hebr
- Latn
- Mlym
- Syrc
keywords:
- handwritten-text-recognition
- optical-character-recognition
- htr
- ocr
- kraken
- ppocr
- ppocrv6
- multilingual
variant_of:
- https://doi.org/10.5281/zenodo.21788403
- https://doi.org/10.5281/zenodo.21788405
model_type:
- recognition
metrics:
  cer: 3.91
  wer: 14.98
  cer_macro: 4.93
  wer_macro: 19.07
datasets:
- Riksarkivet/goteborgs_poliskammare_fore_1900_lines
- Riksarkivet/svea_hovratt_lines
- Riksarkivet/krigshovrattens_dombocker_lines
- Riksarkivet/bergskollegium_relationer_och_skrivelser_lines
- Riksarkivet/frihetstidens_utskottshandlingar_lines
- Riksarkivet/carl_fredrik_pahlmans_resejournaler_lines
- Riksarkivet/trolldomskommissionen_lines
- Riksarkivet/gota_hovratt_lines
- Riksarkivet/bergmastaren_i_nora_htr_lines
- Riksarkivet/alvsborgs_losen_lines
- Riksarkivet/jonkopings_radhusratt_och_magistrat_lines
library_name: kraken
pipeline_tag: image-to-text
tags:
- handwritten-text-recognition
- optical-character-recognition
- htr
- ocr
- kraken
- ppocr
- ppocrv6
- multilingual
---

# PP-OCRv6 (medium) multilingual text recognition base model

> **Hugging Face Hub mirror**
>
> This repository mirrors the [canonical Zenodo release](https://doi.org/10.5281/zenodo.21788410) by
> [Benjamin Kiessling](https://orcid.org/0000-0001-9543-7827), ALMAnaCH, Inria Paris.
> The weights are byte-identical to the Zenodo release and have not been modified by
> [Small Models for GLAM](https://huggingface.co/small-models-for-glam).

## Use from the Hugging Face Hub

Install Kraken and the Hugging Face Hub CLI:

```shell
pip install "kraken>=7.1.0" huggingface_hub
```

Download the model and run recognition:

```shell
hf download small-models-for-glam/kraken-ppocrv6-medium \
    medium.safetensors \
    --local-dir ./kraken-ppocrv6-medium

kraken -i image.png output.txt \
    segment -bl \
    ocr -m ./kraken-ppocrv6-medium/medium.safetensors
```


## Description

This is the **medium** variant (~15.92M parameters) of a family of PP-OCRv6
text-line recognition models (`tiny`, `small`, `medium`) for
[kraken](https://kraken.re). The models are trained from scratch with baseline
+ bounding polygon data with a very diverse corpus containing historical,
contemporary and born-digital document line images, handwritten and
machine-printed, covering 44 languages across 10 scripts (Arabic, Armenian,
Cyrillic, Ethiopic, Georgian, Greek, Hebrew, Latin, Malayalam, and Syriac).

## Architecture

PP-OCRv6 is a conventional CTC-based line recognizer consisting of a lightweight
convolutional backbone and a non-recurrent sequence-modelling neck.

The original architecture published as part of PaddlePaddle has been adapted
for historical ATR by:

* increasing line height to 128px
* uncapping line width/CTC label budget
* replacing the optimizer with Adam+Muon

## Uses

This is a base model that is supposed to produce usable output across a wide
range of scripts and materials out of the box while also allowing fine-tuning
with ease. It should offer similar accuracy and generalization to VLM-based
recognizers without hallucinations and with vastly higher throughput. This
medium variant model achieves the highest scores on the test set, `tiny` and
`small` trade accuracy for inference speed and a smaller memory footprint.

## Transcription guidelines, Normalization, and Transformations

No attempt has been made to normalize the source datasets to a single set of
transcription guidelines; the corpus mixes conventions, so inconsistent output
is to be expected, in particular for Latin-script European manuscripts which
mix large datasets such as CATMuS and TRIDIS that have very different
approaches to transcription. Text was normalized to Unicode **NFD** and
whitespace was normalized during training and evaluation.

## Bias, Risks, and Limitations

The training corpus is heavily skewed towards a handful of high-resource
languages (English, French, German, Latin, Dutch, Middle French, ...). Languages
with little real training material show markedly higher error rates and will
require fine-tuning for practical use. Because transcription conventions are
inconsistent across sources, the model may resolve abbreviations or expand
glyphs unpredictably.

The synthetic data used for training was created with the pangoline tool which
is limited to approximating modern, machine-printed text. For the
languages/scripts present only as synthetic data (Classical Armenian, Geʽez)
and to a lesser extent those sharing the Latin script (Irish, Latvian,
Lithuanian, Romanian, Serbian, Slovenian), real-world accuracy is probably
limited.

## How to Get Started with the Model

Install `kraken` (>= 7.1.0), download the model, and run recognition on an
input image:

```shell
kraken -i image.png output.txt \
    segment -bl \
    ocr -m medium.safetensors
```

For more information, refer to the [documentation](https://kraken.re).

## Training Details

### Training Data

The model was trained on publicly available and restricted (private) datasets.
Datasets marked as *private* are part of the training mixture but are not
redistributable. A **†** marks languages that were additionally
augmented with synthetic training data (see below).

| Language | Script | Datasets |
|----------|:------:|----------|
| Ancient Greek † | Greek | [EPARCHOS](https://zenodo.org/records/4095301), [HPGTR](https://github.com/vivianpl/HPGTR), [HTR_CPgr23](https://gitlab.huma-num.fr/ecrinum/anthologia/htr_cpgr23), [Stavronikita Monastery Greek Handwritten Document Collection No. 114](https://zenodo.org/records/5578251), [Stavronikita Monastery Greek Handwritten Document Collection No. 53](https://zenodo.org/records/5595669), [Stavronikita Monastery Greek Handwritten Document Collection No. 79](https://zenodo.org/records/5578136), 11 private datasets |
| Arabic † | Arabic | [Agapet](https://zenodo.org/records/15473122), [arabic_ms_data](https://github.com/OpenITI/arabic_ms_data), [iskandar](https://github.com/OpenITI/arabic_ms_data), [Muharaf: Manuscripts of Handwritten Arabic Dataset](https://github.com/MehreenMehreen/muharaf), [OpenITI Arabic Print Data](https://github.com/OpenITI/arabic_print_data), [RASAM dataset](https://github.com/calfa-co/rasam-dataset), [TariMa](https://github.com/calfa-co/tarima) |
| Catalan | Latin | [FONDUE-CA-PRINT-20](https://github.com/FoNDUE-HTR/FONDUE-CA-PRINT-20), [htromance-spa](https://github.com/HTRomance-Project/middle-ages-in-spain), 1 private dataset |
| Church Slavonic | Cyrillic | 3 private datasets |
| Classical Armenian † | Armenian | *synthetic only* |
| Corsican | Latin | [OCR Corse](https://github.com/PSL-Chartes-HTR-Students/HN2021-OCR-Poesie-Corse) |
| Czech † | Latin | [2024--medieval-czech-main](https://github.com/HTR-School-Vienna/2024--medieval-czech), [2023--medieval-czech](https://github.com/HTR-School-Vienna/2023--medieval-czech), [HTR Winter School 2025 - Medieval Czech - Biblioteka Jagiellonska BJ Rkp 441 IV](https://github.com/HTR-School-Vienna/2025--medieval-czech), [Paderov Bible handwriting ground truth](https://zenodo.org/records/7467034), [ehri](https://github.com/FloChiff/ehri-dataset) |
| Danish | Latin | [ehri](https://github.com/FloChiff/ehri-dataset) |
| Dutch † | Latin | [6000 ground truth of VOC and notarial deeds / HTR of VOC, WIC and notarial deeds](https://zenodo.org/records/11209325), [ARletta](https://doi.org/10.5281/zenodo.11191457), [Dagboek Ernest Clarysse](https://zenodo.org/records/13769222), [FONDUE-NE-MSS-17-PR](https://github.com/FoNDUE-HTR/FONDUE-NE-MSS-17-PR) |
| English | Latin | [FONDUE-EN-PRINT-20](https://github.com/FoNDUE-HTR/FONDUE-EN-PRINT-20), [IAM Handwriting Database](https://fki.tic.heia-fr.ch/databases/iam-handwriting-database), [jcrs_train](https://zenodo.org/records/4243023), [jcrs_val](https://zenodo.org/records/4243023), [JosephHookerHTR](https://doi.org/10.5281/zenodo.8038689), [OCR-D gt_structure_text](https://github.com/OCR-D/gt_structure_text), [sloanelab](https://github.com/sloanelab-org/HTR-Model), [The Revolutionary City / RevCity documentation](https://americanphilosophicalsociety.github.io/RevCityDocs/), [Memorials for Jane Lathrop Stanford](https://github.com/PSL-Chartes-HTR-Students/HN2021-Memorials_Jane_Lathrop_Stanford), [ehri](https://github.com/FloChiff/ehri-dataset), 2 private datasets |
| Finnish † | Latin | [NewsEye/READ OCR Finnish Newspapers](https://zenodo.org/records/4599472) |
| French | Latin | [Antoine Verard extracts](https://github.com/LaurieHoeben/Verard-corpus), [Copiste-d-un-jour](https://github.com/banq-dcn/Copiste-d-un-jour), [corpus-HTR-lignes-mixtes](https://github.com/Front-Justice/corpus-HTR-lignes-mixtes), [dataset-celestine-doniau-danest](https://github.com/alix-tz/dataset-celestine-doniau-danest), [FONDUE-FR-MSS-19](https://github.com/FoNDUE-HTR/FONDUE-FR-MSS-19), [FONDUE-FR-MSS-19-PR](https://github.com/FoNDUE-HTR/FONDUE-FR-MSS-19-PR), [FONDUE-FR-PRINT-20](https://github.com/FoNDUE-HTR/FONDUE-FR-PRINT-20), [FONDUE-MLT-ART](https://github.com/FoNDUE-HTR/FONDUE-MLT-ART), [genauto-td-htr](https://github.com/jpmjpmjpm/genauto-td-htr), [HTR Front Justice](https://github.com/Front-Justice/htr-front-justice), [La Correspondance Doucet-Rene Jean](https://nakala.fr/10.34847/nkl.48ad8b8d), [Memoire sur St Domingue par H. M. Michel](https://zenodo.org/records/13784411), [Moonshines](https://github.com/alix-tz/moonshines), [NewsEye READ AS French Newspapers](https://zenodo.org/records/5654841), [NuBIS-OCR](https://github.com/ksefil/NuBIS-OCR), [Recensement Valaisan (Valais Time Machine)](https://github.com/PonteIneptique/valais-recensement), [Tapus Corpus](https://github.com/HTR-United/tapuscorpus), [TIMEUS Corpus](https://github.com/HTR-United/timeuscorpus), [TitresNobiliaires_17_18](https://github.com/HisMoDoc-HTR/TitresNobiliaires_17_18), [CREMMA Manuscrits du 20e](https://github.com/HTR-United/CREMMA-MSS-20), [CREMMA Wikipedia](https://github.com/HTR-United/cremma-wikipedia), [Maxime Kovalewsky - Coutume contemporaine et loi ancienne (1893)](https://github.com/PSL-Chartes-HTR-Students/HN2021-Kovalewsky-1893), [HTRomance, Modern Roman languages corpus](https://github.com/HTRomance-Project/modern-roman-languages), [Peraire Ground Truth](https://github.com/alix-tz/peraire-ground-truth), [PARES](https://zenodo.org/records/15719530), 1 private dataset |
| Georgian † | Georgian | 15 private datasets |
| German | Latin | [2024--medieval-german](https://github.com/JulianHelmchen/2024--medieval-german), [2025--Early-Modern-German](https://github.com/HTR-School-Vienna/2025--early-modern-german), [Bullinger Digital Gwalther handwriting ground truth](https://zenodo.org/records/5153263), [charlottenburger-amtsschrifttum](https://github.com/UB-Mannheim/charlottenburger-amtsschrifttum), [Chronicling Germany](https://github.com/Digital-History-Bonn/Chronicling-Germany-Code), [dach-gt](https://github.com/UB-Mannheim/dach-gt), [DigiTheo Ground Truth](https://github.com/tboenig/DTGT), [Dresdner Hofdiarium](https://zenodo.org/records/15303398), [Fibeln](https://github.com/UB-Mannheim/Fibeln), [FONDUE-DE-MSS-16-PR](https://github.com/FoNDUE-HTR/FONDUE-DE-MSS-16-PR), [FONDUE-DE-MSS-18](https://github.com/FoNDUE-HTR/FONDUE-DE-MSS-18), [FONDUE-DE-MSS-19-PR](https://github.com/FoNDUE-HTR/FONDUE-DE-MSS-19-PR), [FONDUE-DE-MSS-20-PR](https://github.com/FoNDUE-HTR/FONDUE-DE-MSS-20-PR), [FONDUE-MLT-ART](https://github.com/FoNDUE-HTR/FONDUE-MLT-ART), [FONDUE-MLT-PRINT-TEST](https://github.com/FoNDUE-HTR/FONDUE-MLT-PRINT-TEST), [FoNDUE_Kunsthistorisches-UZH_Archivdatenbank](https://github.com/FoNDUE-HTR/FoNDUE_Kunsthistorisches-UZH_Archivdatenbank), [Ground truth for Neue Zurcher Zeitung black letter](https://zenodo.org/records/3333627), [Hakenkreuzbanner](https://github.com/UB-Mannheim/Hakenkreuzbanner), [inzigkofen](https://zenodo.org/records/17978574), [Klosterneuburg, Stiftsbibl., Cod. 48](https://zenodo.org/records/7466928), [koenigsfelden](https://zenodo.org/records/5179361), [mkn-kurrent-gt](https://github.com/bertsky/mkn-kurrent-gt), [NewsEye / READ OCR Austrian Newspapers](https://zenodo.org/records/3387369), [nuremberg_letterbooks](https://zenodo.org/records/13881575), [OCR-D gt_structure_text](https://github.com/OCR-D/gt_structure_text), [reichsanzeiger-gt](https://github.com/UB-Mannheim/reichsanzeiger-gt), [Training Data Incunabula Reichenau](https://zenodo.org/records/11046062), [Weisthuemer](https://github.com/UB-Mannheim/Weisthuemer), [gt-fraktur](https://github.com/ubtue/gt-fraktur), [german_kurrent_handwritten_text_lines](https://zenodo.org/records/17252677), [Ground Truth (Tagebücher Edwin Hennig)](https://github.com/ubtue/Ground-Truth), [ehri](https://github.com/FloChiff/ehri-dataset), [Fanny loves Wilhelm](https://zenodo.org/records/15223355), [Frauen im Fokus](https://zenodo.org/records/11038498), [Graphemic Early New German](https://zenodo.org/records/18441031), 1 private dataset |
| German (shorthand) | Latin | 1 private dataset |
| Geʽez † | Ethiopic | *synthetic only* |
| Hebrew | Hebrew | [2025-hebrew](https://github.com/HTR-School-Vienna/2025-hebrew), 2 private datasets |
| Hungarian | Latin | [ehri](https://github.com/FloChiff/ehri-dataset) |
| Irish † | Latin | *synthetic only* |
| Italian | Latin | [Diario del Soldato Bruno Celestino](https://zenodo.org/records/13760586), [EpiSearch HTR](https://github.com/vedph/episearch-htr), [FONDUE-IT-PRINT-20](https://github.com/FoNDUE-HTR/FONDUE-IT-PRINT-20), [FONDUE-IT-PRINT-20-PR](https://github.com/FoNDUE-HTR/FONDUE-IT-PRINT-20-PR), [HTRogène Medieval Italian Manuscripts](https://github.com/HTRogene/italian), [HTRomance, Medieval Italian corpus of ground-truth for Handwritten Text Recognition](https://github.com/HTRomance-Project/medieval-italian), [leopardi](https://github.com/aimagelab/HWD/releases/tag/leopardi), [LiDi1.0-project](https://github.com/Giorgiaagostini/LiDi1.0-project), [LAM](https://aimagelab-legacy.ing.unimore.it/imagelab/page.asp?IdPage=46), 1 private dataset |
| Latin | Latin | [2025--late-medieval-latin-main](https://htr-school-vienna.github.io/2025--late-medieval-latin/), [burchards-dekret-digital](https://gitlab.rlp.net/adwmainz/projekte/burchards-dekret-digital/data.git), [Caroline Minuscule ground truth](https://github.com/rescribe/carolineminuscule-groundtruth), [Carolingian Latin Group HTR Wien Winter School 2025](https://github.com/HTR-School-Vienna/2025--Carolingian_Latin-), [CREMMA Medii Aevi](https://github.com/HTR-United/CREMMA-Medieval-LAT), [DISTINGUO Latin ground truth](https://zenodo.org/records/4780947), [Eutyches](https://github.com/malamatenia/Eutyches), [FONDUE-LA-MSS-16-PR](https://github.com/FoNDUE-HTR/FONDUE-LA-MSS-16-PR), [FONDUE-LA-MSS-17-PR](https://github.com/FoNDUE-HTR/FONDUE-LA-MSS-17-PR), [FONDUE-LA-MSS-MA](https://github.com/FoNDUE-HTR/FONDUE-LA-MSS-MA), [FONDUE-LA-PRINT-16](https://github.com/FoNDUE-HTR/FONDUE-LA-PRINT-16), [HTR Winter School 2023/2024 - Late Medieval Latin, ONB 3891](https://github.com/HTR-School-Vienna/2023--late-medieval-latin), [HTR Winter School 2024/2025 - Late Medieval Latin, ONB 4135; ONB 4680](https://github.com/HTR-School-Vienna/2024--late-medieval-latin), [HTRogène Medieval Latin Manuscripts](https://github.com/HTRogene/latin), [HTRomance, Medieval Latin corpus of ground-truth for Handwritten Text Recognition](https://github.com/HTRomance-Project/medieval-latin), [notarial_charter](https://dl.acm.org/doi/abs/10.1007/978-3-032-04624-6_20), [nubis](https://github.com/ksefil/NuBIS-OCR), [OCR-D gt_structure_text](https://github.com/OCR-D/gt_structure_text), [Paris Bible Project](https://github.com/parisbible/ground_truth), [Training Data Incunabula Reichenau](https://zenodo.org/records/11046062), [Wien ONB Cod 2160 ground truth](https://zenodo.org/records/7537204) |
| Latvian † | Latin | *synthetic only* |
| Lithuanian † | Latin | *synthetic only* |
| Malayalam | Malayalam | [Ground Truth data for printed Malayalam](https://doi.org/10.11588/data/L2KRZO) |
| Middle Dutch | Latin | [data](https://zenodo.org/records/10005366) |
| Middle French | Latin | [Cremma Medieval](https://github.com/HTR-United/cremma-medieval), [De la généalogie des dieux](https://github.com/PSL-Chartes-HTR-Students/HN2021-Boccace), [Données imprimés du 16e siècle](https://github.com/Gallicorpora/HTR-imprime-16e-siecle), [Données HTR incunables du 15e siècle](https://github.com/Gallicorpora/HTR-incunable-15e-siecle), [Données HTR manuscrits du 15e siècle](https://github.com/Gallicorpora/HTR-MSS-15e-Siecle), [Données imprimés du 18e siècle](https://github.com/Gallicorpora/HTR-imprime-18e-siecle), [Données imprimés gothiques du 16e siècle](https://github.com/Gallicorpora/HTR-imprime-16e-siecle), [Fabliaux](https://github.com/CIHAM-HTR/Fabliaux), [FONDUE-FR-AAEB-16](https://github.com/FoNDUE-HTR/FONDUE-FR-AAEB-16), [FONDUE-FR-AAEB-17](https://github.com/FoNDUE-HTR/FONDUE-FR-AAEB-17), [FONDUE-FR-MSS-18](https://github.com/FoNDUE-HTR/FONDUE-FR-MSS-18), [FONDUE-FR-PRINT-16](https://github.com/FoNDUE-HTR/FONDUE-FR-PRINT-16), [FONDUE-FR-PRINT-17](https://github.com/FoNDUE-HTR/FONDUE-FR-PRINT-17), [HTR-SETAF-Jean-Michel](https://github.com/SETAFDH/HTR-SETAF-Jean-Michel), [HTR-SETAF-LesFaictzJCH](https://github.com/SETAFDH/HTR-SETAF-LesFaictzJCH), [HTR-SETAF-Pierre-de-Vingle](https://github.com/SETAFDH/HTR-SETAF-Pierre-de-Vingle), [HTRogene French](https://github.com/HTRogene/french), [HTRomance, Medieval French corpus of ground-truth for Handwritten Text Recognition](https://github.com/HTRomance-Project/medieval-french), [Imprimés 17e siècle](https://github.com/Gallicorpora/HTR-imprime-17e-siecle), [Liber](https://github.com/CIHAM-HTR/Liber), [OCR17plus](https://github.com/e-ditiones/OCR17), [TNAH-2021-DecameronFR](https://github.com/PSL-Chartes-HTR-Students/TNAH-2021-DecameronFR), [transcription-chastel](https://github.com/LaBretelle/transcription-chastel) |
| Multilingual (mixed) | Latin | [Training Data Incunabula Reichenau](https://zenodo.org/records/11046062), [TranscriboQuest25_MedVernacReligio](https://doi.org/10.5281/zenodo.15030337) |
| Norwegian | Latin | [NorHand v3 / Dataset for Handwritten Text Recognition in Norwegian](https://zenodo.org/records/10255840) |
| Occitan | Latin | [HTRogène Medieval Occitan Manuscripts](https://github.com/HTRogene/occitan), 1 private dataset |
| Ottoman Turkish | Arabic | [mehmed_ibn_mehmed_uskubi_cukrikcizade_altiparmak_risale](https://github.com/OpenITI/arabic_ms_data), [OpenITI Arabic-script OCR Catalyst Project print/typeface data](https://github.com/OpenITI/arabic_print_data) |
| Persian † | Arabic | [hafiz_divan](https://github.com/OpenITI/arabic_ms_data), [OpenITI Arabic-script OCR Catalyst Project print/typeface data](https://github.com/OpenITI/arabic_print_data), [sadi_gulistan](https://github.com/OpenITI/arabic_ms_data) |
| Picard | Latin | 1 private dataset |
| Polish † | Latin | [ehri](https://github.com/FloChiff/ehri-dataset) |
| Portuguese | Latin | [iForal-Dataset](https://github.com/Arch-W/iForal-Dataset), [Portuguese Handwriting 16th-19th c.](https://zenodo.org/records/13986218) |
| Romanian † | Latin | *synthetic only* |
| Russian † | Cyrillic | 2 private datasets |
| Serbian (Cyrillic) † | Cyrillic | *synthetic only* |
| Slovak | Latin | [Slovensky Supermodel P&T1](https://zenodo.org/records/11218527), [ehri](https://github.com/FloChiff/ehri-dataset) |
| Slovenian † | Latin | *synthetic only* |
| Spanish | Latin | [FoNDUE Spanish chapbooks 19th c. Dataset](https://github.com/DesenrollandoElCordel/FoNDUE-Spanish-chapbooks-Dataset), [FONDUE-ES-MSS-19-PR](https://github.com/FoNDUE-HTR/FONDUE-ES-MSS-19-PR), [FONDUE-ES-PRINT-19](https://github.com/FoNDUE-HTR/FONDUE-ES-PRINT-19), [HTR - Araucania manuscript XIX](https://github.com/Proyecto-Ocupacion-Araucania-UChile/HTR_Araucania_XIX), [HTRogène Medieval Spanish Manuscripts](https://github.com/HTRogene/spanish), [HTRomance, Medieval Spain corpus of ground-truth for Handwritten Text Recognition](https://github.com/HTRomance-Project/middle-ages-in-spain), [ohg](https://zenodo.org/records/1322666), 3 private datasets |
| Swedish | Latin | [Finnish Court Records-sub500](https://zenodo.org/records/3945088), [kat57 Swedish ground truth dataset](https://zenodo.org/records/14679534), [NewsEye / READ OCR training dataset from Swedish Newspapers](https://zenodo.org/records/4599624), [riskarchiv](https://huggingface.co/collections/Riksarkivet/training-data-for-swedish-lion-libre) |
| Syriac † | Syriac | [zenodo.18157525](https://doi.org/10.5281/zenodo.18157525), [winter_school_vienna](https://zenodo.org/records/14714089), 2 private datasets |
| Ukrainian | Cyrillic | 1 private dataset |
| Urdu | Arabic | [OpenITI Arabic-script OCR Catalyst Project print/typeface data](https://github.com/OpenITI/arabic_print_data) |
| Yiddish | Hebrew | 7 private datasets |

### Synthetic Training Data

Synthetic line images were generated as additional training material for
18 languages: Ancient Greek, Arabic, Classical Armenian, Czech, Dutch, Finnish, Georgian, Geʽez, Irish, Latvian, Lithuanian, Persian, Polish, Romanian, Russian, Serbian, Slovenian, Syriac.
Of these, eight are present **only** as synthetic data: Classical Armenian, Geʽez, Irish, Latvian, Lithuanian, Romanian, Serbian (Cyrillic), Slovenian.

### Training Procedure and Hyperparameters

The model was trained with kraken (feature/ppocrv6_rec branch).

| | |
|---|---|
| Hardware | 3 × NVIDIA H100 |
| Precision | bf16-mixed |
| Optimizer | AdamW + Muon (momentum 0.95, weight decay 0.01) |
| Learning rate | 1.05e-3 (cosine schedule, 3000 step warmup, min 1e-5) |
| Batch size | 96 |
| Gradient clipping | 1.0 |
| Epochs | 12 |
| Normalization | NFD + whitespace |
| Augmentation | enabled |

## Evaluation

### Testing Data

Metrics are computed on a held-out test set for each language. The test split
was obtained by random 5% split with an upper limit of 100 document pages per
language. No attempt has been made to split in a manner that separates documents
between train and test. The scores below are therefore best read as in-domain
generalization.

Evaluations with purely synthetic data are marked with **‡**. CER and WER are
the character- and word-level error rates, computed with `torchmetrics` using
greedy CTC decoding and the NFD + whitespace normalization (equivalent to
`ketos test -u NFD -n`).

### Metrics

| Language | Lines | CER (%) | WER (%) |
|----------|------:|--------:|--------:|
| Ancient Greek | 451 | 7.21 | 44.03 |
| Arabic | 1,926 | 9.38 | 38.90 |
| Catalan | 128 | 2.10 | 11.84 |
| Church Slavonic | 6,599 | 7.53 | 33.66 |
| Classical Armenian ‡ | 3,580 | 0.06 | 0.35 |
| Corsican | 50 | 0.58 | 3.14 |
| Czech | 922 | 7.38 | 37.14 |
| Danish | 25 | 0.48 | 4.46 |
| Dutch | 4,384 | 6.86 | 27.85 |
| English | 2,005 | 5.90 | 20.35 |
| Finnish | 7,907 | 0.63 | 3.97 |
| French | 5,967 | 7.56 | 14.63 |
| Georgian | 394 | 12.75 | 51.15 |
| German | 3,007 | 1.62 | 7.20 |
| German (shorthand) | 830 | 17.46 | 47.69 |
| Geʽez ‡ | 2,992 | 0.11 | 0.46 |
| Hebrew | 3,426 | 5.06 | 14.21 |
| Hungarian | 38 | 2.40 | 16.67 |
| Irish ‡ | 2,824 | 0.14 | 0.68 |
| Italian | 2,611 | 2.89 | 10.90 |
| Latin | 5,748 | 6.45 | 23.91 |
| Latvian ‡ | 2,397 | 0.29 | 1.56 |
| Lithuanian ‡ | 2,615 | 0.48 | 2.45 |
| Malayalam | 59 | 26.18 | 84.96 |
| Middle Dutch | 3,014 | 6.77 | 25.42 |
| Middle French | 3,970 | 3.41 | 15.46 |
| Multilingual (mixed) | 241 | 1.00 | 5.42 |
| Norwegian | 2,335 | 5.22 | 19.27 |
| Ottoman Turkish | 451 | 5.92 | 27.19 |
| Persian | 990 | 4.66 | 20.46 |
| Polish | 2,766 | 0.42 | 2.44 |
| Portuguese | 2,763 | 10.06 | 38.45 |
| Romanian ‡ | 2,412 | 0.38 | 1.85 |
| Russian | 3,053 | 12.34 | 37.21 |
| Serbian (Cyrillic) ‡ | 2,789 | 0.04 | 0.21 |
| Slovak | 1,550 | 2.62 | 10.70 |
| Slovenian ‡ | 2,741 | 1.34 | 3.02 |
| Spanish | 5,465 | 4.49 | 17.61 |
| Swedish | 3,555 | 3.56 | 16.61 |
| Syriac | 1,801 | 4.80 | 21.72 |
| Ukrainian | 1,253 | 5.27 | 21.96 |
| Urdu | 1,656 | 3.77 | 16.77 |
| Yiddish | 4,320 | 4.49 | 16.24 |
| **Aggregate (micro-average)** | 108,010 | **3.91** | **14.98** |
| **Aggregate (macro-average)** | | **4.93** | **19.07** |

### Full-page olmOCR-bench (community evaluation)

On 9 September 2026, a community evaluation combined this recognizer with
Kraken's bundled BLLA segmenter on all **1,403 pages / 8,413 tests** in
[olmOCR-bench](https://huggingface.co/datasets/allenai/olmOCR-bench).
Pages were rendered at 300 DPI and processed through Kraken's Python API on
Hugging Face Jobs. Output was raw newline-joined text, without table
reconstruction, LaTeX generation or header suppression.

| Task | Score (%) |
|---|---:|
| **Overall** | **36.8** |
| Long / tiny text | 74.4 |
| Multiple columns | 57.9 |
| Headers / footers | 37.5 |
| Old scans | 24.1 |
| Tables | 0.2 |
| Old scans: math | 0.0 |
| ArXiv math | 0.0 |
| Automatic baseline | 100.0 |

The official overall score has a **95% bootstrap confidence interval of
35.9–37.7%**. These are full-pipeline test pass rates, including segmentation,
reading order and output format; they are separate from the line-recognition
CER/WER evaluation above. The table score includes two passing baseline checks;
no table-structure tests passed. Baseline checks do not measure transcription
accuracy.

[Reproduction scripts](https://github.com/davanstrien/ocr-bench/tree/main/experiments/kraken-olmocr-bench)
· [Pinned run report and configuration](https://github.com/davanstrien/ocr-bench/blob/741ebffe677054adf900789a5fcbac371e3b7c4b/experiments/kraken-olmocr-bench/RESULTS-2026-09-09.md)
· [Public results and provenance](https://huggingface.co/buckets/davanstrien/kraken-olmbench-results-20260909).

## License

Released under the Apache-2.0 license.

## Acknowledgements

Training of this model was funded by the European Union under Grant Agreement
No.~101132163 (ATRIUM) and No.~101071829 (MiDRASH). Views and opinions
expressed are those of the authors only and do not necessarily reflect those of
the European Union.

This project also received funding from the BPI Scribe project.

## Citation

If you use this model, please cite kraken and if possible credit the dataset
providers linked in the front matter and the table above.
