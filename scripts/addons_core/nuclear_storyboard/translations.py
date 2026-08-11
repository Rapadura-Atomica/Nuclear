"""Tradução da interface (RF: UI em inglês e português).

O Blender traduz a partir do inglês, então as strings do código-fonte estão em
inglês e a versão em português vive neste dicionário. O idioma segue o do
próprio Nuclear (Preferences > Interface > Translation) — não inventamos um
seletor próprio, que só brigaria com o do programa.

Textos gerados em tempo de execução (mensagens de operador) passam por `_()`,
que é `pgettext_iface`.
"""

from __future__ import annotations

import bpy

TRANSLATION_DOMAIN = "nuclear_storyboard"

#: Contexto próprio do add-on.
#:
#: Sem ele o dicionário NATIVO do Blender vence o nosso nas palavras que ele já
#: conhece — "Project" saía como "Projetar" e "Canvas" como "Lonas". Num
#: contexto só nosso, a tradução do add-on é a única candidata.
CTX = "NuclearStoryboard"


def _(text: str) -> str:
    """Traduz uma string de interface no idioma ativo."""
    return bpy.app.translations.pgettext_iface(text, CTX)


def apply_context(classes) -> None:
    """Faz as classes traduzirem `bl_label`/`bl_description` no contexto do add-on.

    Sem isto o Blender procura o `bl_label` de um operador no contexto
    "Operator", onde o add-on não registrava nada — e todo botão ficava em
    inglês mesmo com o dicionário carregado.
    """
    for cls in classes:
        cls.bl_translation_context = CTX


#: (contexto, original em inglês) -> tradução
PT_BR = {
    # --- painéis -----------------------------------------------------
    ("*", "Storyboard"): "Storyboard",
    ("*", "More options"): "Mais opções",
    ("*", "Project"): "Projeto",
    ("*", "Story"): "História",
    ("*", "Canvas"): "Canvas",
    ("*", "Export"): "Exportar",
    ("*", "Library"): "Biblioteca",
    ("*", "Shared with the other scenes"): "Dividida com as outras cenas",
    ("*", "Board"): "Board",
    ("*", "Take on screen"): "Take na tela",
    ("*", "Writes the take code on the camera frame and squares the "
          "drawings on the timeline"):
        "Escreve o código do take no quadro da câmera e desenha os desenhos "
        "como quadrados na timeline",
    ("*", "Open this take"): "Abrir este take",
    ("*", "Draw the board"): "Desenhar o board",

    # --- a coluna de planos (aba Storyboard do Properties) ------------
    ("*", "takes in the Storyboard tab"): "planos na aba Storyboard",
    ("*", "or open a board in the Storyboard tab of the sidebar"):
        "ou abra um board na aba Storyboard da barra lateral",
    ("*", "Renders the missing thumbnails of this scene in a separate process"):
        "Renderiza as miniaturas que faltam nesta cena, num processo à parte",
    ("*", "Redo the ones already there"): "Refazer as que já existem",
    ("*", "board drawn"): "board desenhado",

    # --- projeto -----------------------------------------------------
    ("*", "Project folder"): "Pasta do projeto",
    ("*", "Folder holding project.json, library.json and the media"):
        "Pasta onde ficam project.json, library.json e as mídias",
    ("*", "Project name"): "Nome do projeto",
    ("*", "New project"): "Novo projeto",
    ("*", "Creates the project folder with project.json and library.json"):
        "Cria a pasta do projeto com project.json e library.json",
    ("*", "Open project"): "Abrir projeto",
    ("*", "Loads project.json from the given folder"):
        "Carrega o project.json da pasta indicada",
    ("*", "Save project"): "Salvar projeto",
    ("*", "Writes project.json and library.json"):
        "Grava project.json e library.json",
    ("*", "Open takes folder"): "Abrir pasta dos takes",
    ("*", "Opens the board in this folder, or starts one there — the "
          "episode and the scene come from the path"):
        "Abre o board desta pasta, ou começa um ali — o episódio e a cena "
        "vêm do caminho",
    ("*", "choose the folder where the takes go"):
        "escolha a pasta onde os takes vão ficar",
    ("*", "board opened"): "board aberto",
    ("*", "Dropbox link"): "Link do Dropbox",
    ("*", "Paste the folder link from Dropbox and it opens the local folder"):
        "Cole o link da pasta no Dropbox e ele abre a pasta local",
    ("*", "this folder is not synced on this machine"):
        "esta pasta não está sincronizada nesta máquina",
    ("*", "this link does not say where the folder is"):
        "este link não diz em que pasta o material está",
    ("*", "board started at"): "board começado em",
    ("*", "Lately"): "Recentes",
    ("*", "episode opened"): "episódio aberto",
    ("*", "Close episode"): "Fechar episódio",
    ("*", "Episode folder"): "Pasta do episódio",
    ("*", "Folder holding this episode's scenes"):
        "Pasta onde ficam as cenas deste episódio",
    ("*", "no scene in this folder yet"): "nenhuma cena nesta pasta ainda",
    ("*", "Creates the scene folder inside the episode and opens it"):
        "Cria a pasta da cena dentro do episódio e entra nela",
    ("*", "open the episode folder first"): "abra a pasta do episódio primeiro",
    ("*", "scene created"): "cena criada",
    ("*", "this scene already existed"): "esta cena já existia",
    ("*", "board started in the folder that was there"):
        "board começado na pasta que já estava lá",
    ("*", "Forget this board"): "Esquecer este board",
    ("*", "Open board folder"): "Abrir a pasta do board",
    ("*", "Close project"): "Fechar projeto",
    ("*", "Saves and closes the current project"):
        "Salva e fecha o projeto atual",
    ("*", "Validate project"): "Validar projeto",
    ("*", "Runs the PRD rules and lists what blocks the export"):
        "Roda as regras do PRD e lista o que impede o export",
    ("*", "Timeline"): "Timeline",

    # --- estrutura ---------------------------------------------------
    ("*", "Episodes"): "Episódios",
    ("*", "Scenes"): "Cenas",
    ("*", "Takes"): "Takes",
    ("*", "Episode"): "Episódio",
    ("*", "Scene"): "Cena",
    ("*", "New episode"): "Novo episódio",
    ("*", "New scene"): "Nova cena",
    ("*", "New take"): "Novo take",
    ("*", "Remove take"): "Remover take",
    ("*", "Move take"): "Mover take",
    ("*", "Code"): "Código",
    ("*", "Name"): "Nome",
    ("*", "scene(s)"): "cena(s)",
    ("*", "take(s)"): "take(s)",
    ("*", "No take selected"): "Nenhum take selecionado",
    ("*", "Select a take in the story"): "Selecione um take na história",

    # --- take: desenhos e áudio --------------------------------------
    ("*", "drawings"): "desenhos",
    ("*", "minimum not reached"): "mínimo não atingido",
    ("*", "Duration"): "Duração",
    ("*", "automatic"): "automática",
    ("*", "manual"): "manual",
    ("*", "Audio"): "Áudios",
    ("*", "no audio: duration falls back to the default"):
        "sem áudio: a duração cai no padrão",
    ("*", "Import audio"): "Importar áudio",
    ("*", "Copies a .wav into the project and adds it to the take"):
        "Copia um .wav para dentro do projeto e adiciona ao take",
    ("*", "Remove audio"): "Remover áudio",
    # --- RF-18: editor de áudio externo ------------------------------
    ("*", "Edit in Audacity"): "Editar no Audacity",
    ("*", "Opens the clip .wav in the external audio editor; when it is saved "
          "the take reloads by itself"):
        "Abre o .wav do clipe no editor de áudio externo; quando ele salvar, o "
        "take recarrega sozinho",
    ("*", "Reload audio"): "Recarregar áudio",
    ("*", "Rereads the .wav from disk and updates the clip duration"):
        "Relê o .wav do disco e atualiza a duração do clipe",
    ("*", "audio open in the editor"): "áudio aberto no editor",
    ("*", "reloaded from the editor"): "recarregado do editor",
    ("*", "Audio editor"): "Editor de áudio",
    ("*", "Path to Audacity; empty finds it in PATH or Flatpak (RF-18)"):
        "Caminho do Audacity; vazio procura no PATH ou no Flatpak (RF-18)",
    ("*", "Place audio"): "Posicionar áudio",
    ("*", "Start (s)"): "Início (s)",
    ("*", "Take duration"): "Duração do take",
    ("*", "Duration (s)"): "Duração (s)",
    ("*", "How long this plan lasts, in seconds"):
        "Quanto este plano dura, em segundos",
    ("*", "Back to automatic"): "Voltar ao automático",

    # --- canvas ------------------------------------------------------
    ("*", "Open take in canvas"): "Abrir take no canvas",
    ("*", "Open in Canvas"): "Abrir no Canvas",
    ("*", "Remove other takes' art"): "Remover arte de outro take",
    ("*", "Removes Grease Pencil objects of OTHER takes left inside this file; "
          "objects with drawings are kept"):
        "Remove objetos de Grease Pencil de OUTROS takes que sobraram neste "
        "arquivo; objetos com desenho são mantidos",
    ("*", "object(s) from another take"): "objeto(s) de outro take",
    ("*", "object(s) removed"): "objeto(s) removidos",
    ("*", "kept because they have drawings"): "mantidos porque têm desenho",
    ("*", "Opens (or creates) the take .nuc and sets the drawing scene up"):
        "Abre (ou cria) o .nuc do take e monta a cena de desenho",
    ("*", "Save take"): "Salvar take",
    ("*", "Writes the .nuc and updates the take drawing index"):
        "Grava o .nuc e atualiza o índice de desenhos do take",
    ("*", "New drawing"): "Novo desenho",
    ("*", "Creates a new keyframe on the content layers and jumps to it"):
        "Cria um keyframe novo nas camadas de conteúdo e pula para ele",
    ("*", "Remove drawing"): "Remover desenho",
    ("*", "Go to drawing"): "Ir para o desenho",
    ("*", "Character layer"): "Camada do personagem",
    ("*", "Layers"): "Camadas",
    ("*", "active"): "ativa",
    ("*", "Drawings"): "Desenhos",
    ("*", "Rebuild take canvas"): "Recriar canvas do take",
    ("*", "Grayscale background (RN02)"): "BG em escala de cinza (RN02)",
    ("*", "Convert background to gray"): "Converter o fundo para cinza",
    ("*", "Background is clean"): "BG limpo",
    ("*", "color problem(s) in the background"): "problema(s) de cor no BG",

    # --- timeline ----------------------------------------------------
    ("*", "Build"): "Montar",
    ("*", "Read"): "Ler",
    ("*", "audio clip(s)"): "clipe(s) de áudio",
    ("*", "clip(s) outside the take"): "clipe(s) fora do take",
    ("*", "Frame timing"): "Timing dos frames",
    ("*", "keyframes are off the planned spread"):
        "keyframes fora da distribuição planejada",

    # --- biblioteca --------------------------------------------------
    ("*", "Characters (colour -> rig)"): "Personagens (cor → rig)",
    ("*", "Props"): "Props",
    ("*", "New character"): "Novo personagem",
    ("*", "Registers a character with the lineart color and the final rig"):
        "Cadastra personagem com a cor do lineart e o rig final",
    ("*", "Lineart color"): "Cor do lineart",
    ("*", "Colour this character's lineart is drawn with"):
        "Cor com que o lineart deste personagem é desenhado",
    ("*", "Lineart colour of this character — click to pick"):
        "Cor do lineart deste personagem — clique para escolher",
    ("*", "Colour code"): "Código da cor",
    ("*", "Remove character"): "Remover personagem",
    ("*", "Link rig"): "Vincular rig",
    ("*", "drawing with"): "desenhando com",
    ("*", "Bring prop into the take"): "Trazer o prop para o take",
    ("*", "Puts the selected prop's art into the take being drawn, behind the "
          "drawing"):
        "Põe a arte do prop selecionado no take que está sendo desenhado, atrás "
        "do desenho",
    ("*", "this prop has no art yet"): "este prop ainda não tem arte",
    ("*", "the prop art is missing"): "a arte do prop sumiu do lugar",
    ("*", "prop brought into the take"): "prop trazido para o take",
    ("*", "prop art updated"): "arte do prop atualizada",
    ("*", "New prop"): "Novo prop",
    ("*", "Replace with final version"): "Substituir por versão final",
    ("*", "Character"): "Personagem",
    ("*", "Prop"): "Prop",
    ("*", "Hex color"): "Cor hex",
    ("*", "Temporary"): "Temporário",
    ("*", "temporary"): "temporário",
    ("*", "Provisional version, still to be replaced"):
        "Versão provisória, ainda será substituída",
    ("*", "no rig"): "sem rig",
    ("*", "Color"): "Cor",
    ("*", "Rig"): "Rig",

    # --- export ------------------------------------------------------
    ("*", "Render take drawings"): "Renderizar desenhos do take",
    ("*", "Renders the selected take PNGs in a separate process"):
        "Gera os PNGs do take selecionado, num processo separado",
    ("*", "Export animatic"): "Exportar animatic",
    ("*", "Renders what is missing and builds the MP4 with burn-in and the "
          ".kdenlive project, in a separate process"):
        "Renderiza o que falta e gera o MP4 com burning e o projeto .kdenlive, "
        "num processo separado",
    ("*", "Open exports folder"): "Abrir pasta de exports",
    ("*", "Re-render existing"): "Re-renderizar existentes",
    ("*", "Re-render everything"): "Re-renderizar tudo",
    ("*", "MP4 video"): "Vídeo MP4",
    ("*", ".kdenlive project"): "Projeto .kdenlive",
    ("*", "drawing(s) rendered"): "desenho(s) renderizados",
    ("*", "Burn-in"): "Burning",
    ("*", "off"): "desligado",
    ("*", "logo"): "logo",
    ("*", "none (text only)"): "nenhuma (só texto)",
    ("*", "error(s) block the export"): "erro(s) impedem o export",
    ("*", "ffmpeg not found in PATH"): "ffmpeg não encontrado no PATH",

    # --- validação ---------------------------------------------------
    ("*", "no problems"): "nenhum problema",

    # --- mensagens de operador ---------------------------------------
    ("*", "project created at"): "projeto criado em",
    ("*", "project saved"): "projeto salvo",
    ("*", "export running…"): "export em andamento…",
    ("*", "export finished"): "export concluído",
    ("*", "drawings rendered"): "desenhos renderizados",
    ("*", "animatic exported to"): "animatic exportado em",
    ("*", "choose the project folder"): "escolha a pasta do projeto",
    ("*", "the take has no canvas"): "o take não tem canvas",
    ("*", "project ready for export"): "projeto pronto para export",
    ("*", "pick another prop as the final version"):
        "escolha outro prop como versão final",
    ("*", "nothing changed in the timeline"): "nada mudou na timeline",
    ("*", "background was already grayscale"): "BG já estava em escala de cinza",
    ("*", "project opened"): "projeto aberto",
    ("*", "take opened"): "take aberto",
    ("*", "take removed from the index; files stay on disk"):
        "take removido do índice (os arquivos ficam no disco)",
    ("*", "audio imported"): "áudio importado",
    ("*", "this color already belongs to another character"):
        "esta cor já pertence a outro personagem",
    ("*", "rig linked"): "rig vinculado",
    ("*", "problem(s) block the export"): "problema(s) impedem o export",
    ("*", "drawing(s) saved to"): "desenho(s) salvos em",
    ("*", "drawing"): "desenho",
    ("*", "character layer ready"): "camada do personagem pronta",
    ("*", "background color(s) turned gray"): "cor(es) do BG convertidas para cinza",
    ("*", "gray lock on: the brush stays gray on the background layer"):
        "trava ligada: o pincel fica cinza na camada de BG",
    ("*", "gray lock off"): "trava do BG desligada",
    ("*", "clip(s) on the timeline"): "clipe(s) na timeline",
    ("*", "clip(s) updated in the take"): "clipe(s) atualizados no take",
    ("*", "exposure read from"): "exposição lida de",
    ("*", "drawing(s)"): "desenho(s)",
    ("*", "drawing(s) repositioned"): "desenho(s) reposicionados",
    ("*", "manual exposure(s) cleared"): "exposição(ões) manuais limpas",
    ("*", "could not start the worker"): "não deu para iniciar o worker",
    ("*", "the worker failed"): "o worker falhou",
    ("*", "animatic exported"): "animatic exportado",
    ("*", "New Project"): "Novo Projeto",
    ("*", "Valid"): "Válido",
    ("*", "Final prop index"): "Índice do prop final",

    # --- drag-and-drop -----------------------------------------------
    ("*", "Drop audio into the take"): "Soltar áudio no take",
    ("*", "Imports the dropped .wav files into the open take"):
        "Importa os .wav soltos na janela para o take aberto",
    ("*", "Storyboard dialogue audio"): "Áudio de diálogo do storyboard",
    ("*", "One after another"): "Um depois do outro",

    # --- RF-09: o prop sai do próprio desenho -------------------------
    ("*", "Art"): "Arte",
    ("*", "Automatic"): "Automática",
    ("*", "Layer being drawn, objects group or the frame"):
        "Camada em que se está desenhando, grupo de objetos ou o quadro",
    ("*", "Active layer"): "Camada ativa",
    ("*", "Only the layer being drawn on"): "Só a camada em que se está desenhando",
    ("*", "Objects group"): "Grupo de objetos",
    ("*", "Every layer in the objects group"): "Todas as camadas do grupo de objetos",
    ("*", "Whole frame"): "Quadro inteiro",
    ("*", "The plan as it is on screen"): "O plano como está na tela",
    ("*", "Register with no art at all"): "Cadastrar sem arte nenhuma",
    ("*", "Reference"): "Referência",
    ("*", "the drawing on the layer you are on"):
        "o desenho da camada em que você está",
    ("*", "what is drawn in the objects group"):
        "o que está desenhado no grupo de objetos",
    ("*", "this plan's frame"): "o quadro deste plano",
    ("*", "nothing yet — the request waits for a picture"):
        "nada ainda — a pendência espera uma imagem",
    ("*", "the picture you chose"): "a imagem que você escolheu",
    ("*", "Picture (optional)"): "Imagem (opcional)",
    ("*", "Only if you already have one — without it the drawing itself is used"):
        "Só se você já tiver uma — sem ela vale o próprio desenho",
    ("*", "prop created"): "prop criado",
    ("*", "Draw this character"): "Desenhar este personagem",
    ("*", "Gets the take ready to draw this character: his layer active and the "
          "brush on his colour"):
        "Deixa o take pronto para desenhar este personagem: a camada dele ativa "
        "e o pincel na cor dele",

    # --- RF-13: recorte do export e prévia da cena -------------------
    ("*", "Watch scene"): "Assistir à cena",
    ("*", "Builds the animatic of the selected scene only and opens it in the player"):
        "Monta o animatic só da cena selecionada e abre no player",
    ("*", "Scope"): "Escopo",
    ("*", "Whole project"): "Projeto inteiro",
    ("*", "Every take, in document order"): "Todos os takes, na ordem do documento",
    ("*", "Selected episode"): "Episódio selecionado",
    ("*", "Every take of the selected episode"): "Todos os takes do episódio selecionado",
    ("*", "Selected scene"): "Cena selecionada",
    ("*", "Every take of the selected scene (RF-13)"):
        "Todos os takes da cena selecionada (RF-13)",
    ("*", "Selected take"): "Take selecionado",
    ("*", "Only the selected take"): "Só o take selecionado",
    ("*", "Play when finished"): "Tocar ao terminar",
    ("*", "Opens the exported video in the system player"):
        "Abre o vídeo exportado no player do sistema",
    ("*", "nothing selected to export"): "nada selecionado para exportar",

    # --- RF-14: burning ----------------------------------------------
    ("*", "Space the drawings evenly"): "Espalhar os desenhos por igual",
    ("*", "Clears the timing set by hand and spreads the drawings over the take "
          "duration — the drawings themselves are untouched"):
        "Desfaz o tempo ajustado na mão e espalha os desenhos pela duração do "
        "take — o desenho em si não é tocado",
    # --- 2026-07-29: linguagem do artista (menos jargão) --------------
    ("*", "dr."): "des.",
    ("*", "thing to fix"): "coisa para resolver",
    ("*", "things to fix"): "coisas para resolver",
    ("*", "Create a take to start"): "Crie um take para começar",
    ("*", "Draw"): "Desenhar",
    ("*", "no drawing yet"): "ainda sem desenho",
    ("*", "Cut take here"): "Cortar o take aqui",
    ("*", "Save to"): "Salvar em",
    ("*", "Folder the animatic goes to — point it at the production folder to "
          "deliver straight from here; empty keeps it inside the project"):
        "Pasta para onde o animatic vai — aponte para a pasta da produção e "
        "entregue direto daqui; vazio deixa dentro do projeto",
    ("*", "cannot write to this folder"): "não dá para gravar nesta pasta",
    ("*", "Splits the take in two at the current frame: what comes "
          "after becomes the next take of the scene"):
        "Parte o take em dois no quadro atual: o que vem depois vira o "
        "próximo take da cena",
    ("*", "take split at frame"): "take partido no quadro",
    ("*", "this take is not in the project anymore"):
        "este take não está mais no projeto",
    ("*", "no dialogue yet"): "sem diálogo ainda",
    ("*", "there is art from another take here"): "há arte de outro take aqui",
    ("*", "drawing(s) were never saved to the file"):
        "desenho(s) nunca chegaram a ser salvos no arquivo",
    ("*", "colour(s) in the background"): "cor(es) no fundo",

    ("*", "only .wav files are accepted"): "só arquivos .wav são aceitos",
    ("*", "audio file(s) imported"): "áudio(s) importados",
    ("*", "ignored (not .wav)"): "ignorado(s) (não é .wav)",

    # --- 2026-08-06: painel de entrega --------------------------------
    ("*", "Delivery"): "Entrega",
    ("*", "How to deliver"): "Como entregar",
    ("*", "Deliver"): "Entregar",
    ("*", "What to deliver"): "O que entregar",
    ("*", "This take"): "Este take",
    ("*", "Only the take on screen"): "Só o take que está na tela",
    ("*", "This scene"): "Esta cena",
    ("*", "Every take of the scene"): "Todos os takes da cena",
    ("*", "This episode"): "Este episódio",
    ("*", "Every take of the episode"): "Todos os takes do episódio",
    ("*", "Whole board"): "O board inteiro",
    ("*", "Everything, in order"): "Tudo, na ordem",
    ("*", "plan(s)"): "plano(s)",
    ("*", "nothing selected to deliver"): "nada selecionado para entregar",
    ("*", "Deliver to"): "Entregar em",
    ("*", "A folder (production, Dropbox)"): "Uma pasta (produção, Dropbox)",
    ("*", "The files are written to a folder on this computer"):
        "Os arquivos são gravados numa pasta deste computador",
    ("*", "The approval system (the producer reviews there)"):
        "O sistema de aprovação (é lá que o produtor assiste)",
    ("*", "Uploads the animatic for review, without writing to a folder"):
        "Sobe o animatic para revisão, sem gravar em pasta nenhuma",
    ("*", "The folder and the approval system"): "A pasta e o sistema de aprovação",
    ("*", "Both at once"): "As duas de uma vez",
    ("*", "Scenes in this episode"): "Cenas deste episódio",
    ("*", "What goes in this delivery"): "O que entra nesta entrega",
    ("*", "Where this delivery goes"): "Para onde esta entrega vai",
    ("*", "The animatic (everything joined) goes to"):
        "O animatic (tudo emendado) vai para",
    ("*", "The plans, one file each, go to"):
        "Os planos, um arquivo cada, vão para",
    ("*", "empty: stays in exports, inside the board"):
        "vazio: fica em exports, dentro do board",
    ("*", "empty: stay in exports/takes, inside the board"):
        "vazio: ficam em exports/takes, dentro do board",
    ("*", "Goes to"): "Vai para",
    ("*", "Format"): "Formato",
    ("*", "MP4 (review)"): "MP4 (revisão)",
    ("*", "Plays anywhere; it is what approvals take"):
        "Abre em qualquer lugar; é o que a aprovação recebe",
    ("*", "DNxHR (editing)"): "DNxHR (edição)",
    ("*", "Goes straight into DaVinci"): "Entra direto no DaVinci",
    ("*", "Plays anywhere and is what the approval system takes"):
        "Abre em qualquer lugar e é o que a aprovação recebe",
    ("*", "Cuts frame by frame in DaVinci without converting first"):
        "Corta quadro a quadro no DaVinci, sem converter antes",
    ("*", "Kdenlive project"): "Projeto do Kdenlive",
    ("*", "Also writes the .kdenlive next to the video"):
        "Também grava o .kdenlive ao lado do vídeo",
    ("*", "A video per plan (PROJECT_EP00_C00T00.mp4) besides the animatic — "
          "it is what the animation team gets to work on"):
        "Um vídeo por plano (PROJETO_EP00_C00T00.mp4) além do animatic — é o "
        "arquivo que a animação recebe para animar em cima",
    ("*", "Folder"): "Pasta",
    ("*", "Where the animatic goes; empty keeps it inside the board"):
        "Para onde o animatic vai; vazio deixa dentro do board",
    ("*", "Takes folder"): "Pasta dos takes",
    ("*", "Where the per-take files go; empty keeps them in the board"):
        "Para onde vão os arquivos por take; vazio deixa dentro do board",
    ("*", "Send to approvals"): "Mandar para a aprovação",
    ("*", "Uploads the animatic to the approval system as soon as it is built"):
        "Sobe o animatic para o sistema de aprovação assim que ele fica pronto",
    ("*", "Storyboard: sending to approvals…"):
        "Storyboard: mandando para a aprovação…",
    ("*", "sent to approvals"): "entregue na aprovação",
    ("*", "delivered to the folder, but not sent"):
        "entregue na pasta, mas não enviado",
    ("*", "the video was not built; nothing was sent"):
        "o vídeo não foi montado; nada foi enviado",
    ("*", "to send, the animatic itself has to be built"):
        "para enviar, o animatic precisa ser montado",
    ("*", "approvals only take MP4 — deliver in MP4 and keep the other format "
          "for editing"):
        "a aprovação só recebe MP4 — entregue em MP4 e guarde o outro formato "
        "para a edição",
    ("*", "sign in to approvals first"): "entre na aprovação primeiro",
    ("*", "Animatic exported from the storyboard"):
        "Animatic exportado do storyboard",
    ("*", "thing(s) to fix in the board"): "coisa(s) a resolver no board",

    # --- 2026-08-04: entrega take a take ------------------------------
    ("*", "Animatic (takes joined)"): "Animatic (takes emendados)",
    ("*", "One file per take"): "Um arquivo por take",
    # --- 2026-08-10: take a take ligado, e escrito na tela de entrega --
    ("*", "One MP4 per plan"): "Um MP4 por plano",
    ("*", "one per plan"): "um por plano",
    ("*", "like"): "tipo",
    ("*", "Also export take by take"): "Sair também take a take",
    ("*", "Also writes one MP4 per take, named PROJECT_EP00_C00T00 — this is "
          "what the animation team receives"):
        "Também gera um MP4 por take, no nome PROJETO_EP00_C00T00 — é o "
        "arquivo que a animação recebe",
    ("*", "Takes go to"): "Takes vão para",
    ("*", "Folder the individual takes go to; empty keeps them in "
          "exports/takes inside the project"):
        "Pasta para onde vão os takes avulsos; vazio deixa em exports/takes, "
        "dentro do projeto",
    ("*", "file(s), like"): "arquivo(s), tipo",
    ("*", "Export take"): "Exportar o take",
    ("*", "takes exported to"): "takes exportados em",
    ("*", "nothing to export: pick at least one file"):
        "nada a exportar: marque pelo menos um arquivo",
    ("*", "File names"): "Nome dos arquivos",
    ("*", "Project code"): "Sigla do projeto",
    ("*", "Short code that opens every delivered file name (DPE_EP03_C02T05); "
          "empty uses the board name"):
        "Sigla que abre o nome de cada arquivo entregue (DPE_EP03_C02T05); "
        "vazio usa o nome do board",
    ("*", "Files will be named"): "Os arquivos vão se chamar",

    # --- 2026-08-04: ponte com o sistema de aprovação ------------------
    ("*", "Files start with"): "Os arquivos começam com",
    ("*", "Sets the code that opens the name of every delivered file"):
        "Define a sigla que abre o nome de cada arquivo entregue",
    ("*", "Approvals address"): "Endereço do aprovação",
    ("*", "Address of the approval API; empty uses the studio one"):
        "Endereço da API de aprovação; vazio usa o do estúdio",
    ("*", "Sign in to approvals"): "Entrar no aprovação",
    ("*", "Signs in with the same user and password as the intranet, so the "
          "board can open pending items there"):
        "Entra com o mesmo usuário e senha da intranet, para o board poder "
        "abrir pendências lá",
    ("*", "Sign out"): "Sair",
    ("*", "signed in as"): "entrou como",
    ("*", "signed out"): "saiu do aprovação",
    ("*", "User"): "Usuário",
    ("*", "Password"): "Senha",
    ("*", "Same user as the intranet"): "O mesmo usuário da intranet",
    ("*", "Link to a project"): "Ligar a um projeto",
    ("*", "Lists the projects from the approval system and links this board to "
          "one of them"):
        "Lista os projetos do sistema de aprovação e liga este board a um deles",
    ("*", "no project available in the approval system"):
        "nenhum projeto disponível no sistema de aprovação",
    ("*", "board linked to"): "board ligado a",
    ("*", "pick a project"): "escolha um projeto",
    ("*", "suggestion"): "sugestão",
    ("*", "no client contact in this project"):
        "este projeto não tem contato de cliente",
    ("*", "this board is not linked to a project yet"):
        "este board ainda não está ligado a um projeto",
    ("*", "Request goes to"): "A pendência vai para",

    ("*", "Attach reference image"): "Anexar imagem de referência",
    ("*", "Attaches the reference image of the temporary prop — it is what goes "
          "to the approval system as the request"):
        "Anexa a imagem de referência do prop provisório — é o que vai para o "
        "sistema de aprovação como pedido",
    ("*", "reference image not found"): "imagem de referência não encontrada",
    ("*", "reference attached"): "referência anexada",
    ("*", "reference attached; request pending"):
        "referência anexada; a pendência ficou para enviar",
    ("*", "Ask the studio to create it"): "Pedir ao estúdio que crie",
    ("*", "Opens a pending item in the approval system, with the reference "
          "attached"):
        "Abre uma pendência no sistema de aprovação, com a referência anexada",
    ("*", "Open the request now"): "Abrir a pendência agora",
    ("*", "Opens the pending item in the approval system right away"):
        "Abre a pendência no sistema de aprovação na hora",
    ("*", "prop created; request pending"):
        "prop criado; a pendência ficou para enviar",
    ("*", "request opened in the approval system"):
        "pendência aberta no sistema de aprovação",
    ("*", "Send pending requests"): "Enviar pendências",
    ("*", "Opens, in the approval system, one pending item per temporary prop "
          "that has a reference image"):
        "Abre, no sistema de aprovação, uma pendência para cada prop provisório "
        "que tem imagem de referência",
    ("*", "request(s) opened"): "pendência(s) abertas",
    ("*", "prop(s) still to request"): "prop(s) ainda por pedir",
    ("*", "no project code yet"): "sigla do projeto não definida",
    ("*", "files use the board name"): "os arquivos usam o nome do board",

    # --- 2026-08-04: corrigir código de episódio/cena/take -------------
    ("*", "Rename"): "Renomear",
    ("*", "Fixes the code and the name of the selected episode, scene and take "
          "— the code is what opens each delivered file name"):
        "Corrige o código e o nome do episódio, da cena e do take selecionados "
        "— é o código que abre o nome de cada arquivo entregue",
    ("*", "Episode code"): "Código do episódio",
    ("*", "Episode name"): "Nome do episódio",
    ("*", "Scene code"): "Código da cena",
    ("*", "Scene name"): "Nome da cena",
    ("*", "Take code"): "Código do take",
    ("*", "Take name"): "Nome do take",
    ("*", "the episode needs a code"): "o episódio precisa de um código",
    ("*", "names updated"): "nomes atualizados",

    # --- 2026-08-10: renomear o projeto depois de criado ---------------
    ("*", "Rename project"): "Renomear o projeto",
    ("*", "Fixes the project name that goes in the burn-in and the code that "
          "opens every delivered file name"):
        "Corrige o nome do projeto que vai no burning e a sigla que abre o "
        "nome de cada arquivo entregue",
    ("*", "Goes in the burn-in of every frame delivered"):
        "Vai no burning de cada quadro entregue",
    ("*", "the project needs a name"): "o projeto precisa de um nome",
    # "Episode", "Scene", "Code" e "Name" já estão traduzidos lá em cima —
    # repetir aqui só criaria duas fontes para a mesma palavra.
    ("*", "Check requests"): "Conferir pendências",
    ("*", "Reads how the requests are doing in the approval system and brings "
          "in the art that has been approved"):
        "Lê como as pendências estão no sistema de aprovação e traz a arte que "
        "já foi aprovada",
    ("*", "request(s) checked"): "pendência(s) conferidas",
    ("*", "resolved"): "resolvida(s)",
    ("*", "no longer there"): "sumiu de lá",
    ("*", "Temporary prop created in the storyboard; needs the final art."):
        "Prop provisório criado no storyboard; precisa da arte final.",
    ("*", "Appears in"): "Aparece em",
    ("*", "Approved art brought from the approval system"):
        "Arte aprovada trazida do sistema de aprovação",

    # estados da pendência na lista de props
    ("*", "to send"): "a enviar",
    ("*", "asked"): "pedido",
    ("*", "with the producer"): "com o produtor",
    ("*", "with the client"): "com o cliente",
    ("*", "changes asked"): "pediram correção",
    ("*", "art ready"): "arte pronta",
    ("*", "turned down"): "recusado",
    ("*", "final art in"): "arte final entrou",
}

def _expand(table: dict) -> dict:
    """Repete cada entrada nos contextos que a interface consulta.

    `CTX` é onde os rótulos do add-on são procurados; "*" e "Operator" cobrem
    o que escapa (mensagens de `report`, rótulos de RNA).
    """
    out = {}
    for (ctx, source), target in table.items():
        for context in (CTX, ctx, "Operator"):
            out[(context, source)] = target
    return out


TRANSLATIONS = {"pt_BR": _expand(PT_BR), "pt": _expand(PT_BR)}


def register():
    try:
        bpy.app.translations.register(TRANSLATION_DOMAIN, TRANSLATIONS)
    except ValueError:
        # Já registrado (recarga do add-on): troca pelo dicionário novo.
        bpy.app.translations.unregister(TRANSLATION_DOMAIN)
        bpy.app.translations.register(TRANSLATION_DOMAIN, TRANSLATIONS)


def unregister():
    try:
        bpy.app.translations.unregister(TRANSLATION_DOMAIN)
    except ValueError:
        pass
