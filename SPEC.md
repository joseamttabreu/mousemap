# mousemap — Especificação do projeto

Versão 0.1 · 15/10/2026

## 1. Visão geral

O mousemap é um app para Linux (GNOME/Wayland) que permite escolher o que cada botão extra do mouse faz, configurado por uma interface gráfica simples. Ele substitui o Logi Options, que não existe para Linux, sem a complexidade do Solaar.

**Problema.** No Fedora com GNOME/Wayland não há ferramenta oficial da Logitech. O Solaar resolve, mas a configuração por regras é pouco intuitiva. O protótipo de 15/10/2026 (`~/mousemap/mousemap.py`) provou que remapear via evdev/uinput funciona, mas só se configura editando TOML.

**Objetivo.** Em menos de 1 minuto e sem terminal, o usuário escolhe uma ação para cada um dos 4 botões extras do MX Anywhere 2S e a mudança vale na hora.

**Público.** Usuários de desktop Linux com mouse de botões extras. Primeiro alvo: MX Anywhere 2S via Bluetooth, Fedora 44, GNOME.

**Princípios**

- Simples antes de completo: poucas ações bem feitas, sem editor de regras.
- Funciona em Wayland: atua no nível do kernel, sem depender do compositor.
- Sem root em tempo de execução: privilégio só na instalação.
- Falha segura: se o serviço cair, o mouse volta ao comportamento original.
- Configuração legível: a GUI grava o mesmo TOML que pode ser editado à mão.

## 2. Escopo

O MVP cobre 4 botões extras de um mouse, configurados por GUI, com ações de atalho, comando e clique. Perfis por aplicativo e vários mouses ficam para fases seguintes.

| Item | MVP | Depois | Fora |
|---|---|---|---|
| Inclinação da roda (esquerda/direita) | sim | | |
| Botões laterais (voltar/avançar) | sim | | |
| Clique do meio e botão abaixo da roda | | sim | |
| Ações: atalho, comando, outro clique, padrão, desativado | sim | | |
| Ações prontas (área de trabalho, volume, mídia, copiar/colar) | sim | | |
| Ações: macro (sequência de teclas), rolagem | | sim | |
| Interface gráfica GTK4/libadwaita | sim | | |
| Escolha do mouse entre os conectados | sim | | |
| Vários mouses configurados ao mesmo tempo | | sim | |
| Perfis por aplicativo (via extensão do GNOME Shell) | | sim | |
| KDE Plasma e X11 | | testar | |
| DPI, SmartShift, bateria (protocolo HID++) | | | sim |
| Gestos (segurar botão e mover o mouse) | | | sim |
| Windows e macOS | | | sim |

DPI e bateria ficam fora porque exigem o protocolo HID++ da Logitech; o GNOME já mostra a bateria.

## 3. Requisitos funcionais

### Daemon (`mousemapd`)

- **RF-01** Capturar com exclusividade (`EVIOCGRAB`) o mouse configurado e reemitir todos os eventos por um mouse virtual (uinput), alterando só os botões mapeados.
- **RF-02** Reconhecer 4 gatilhos: `tilt_left`, `tilt_right` (eventos `REL_HWHEEL`/`REL_HWHEEL_HI_RES` negativos/positivos), `side_back` (`BTN_SIDE`) e `side_forward` (`BTN_EXTRA`).
- **RF-03** Executar, por gatilho, uma destas ações:
  - `default`: repassa o evento original.
  - `none`: descarta o evento.
  - `keys`: emite um atalho por um teclado virtual. Em botões, o atalho fica pressionado enquanto o botão estiver; na inclinação, é um toque.
  - `cmd`: executa um comando do usuário em sessão própria, sem bloquear o daemon.
  - `click`: emite outro botão do mouse (left, right, middle, back, forward).
- **RF-04** Na inclinação mantida, repetir a ação a cada `tilt_cooldown_ms` (padrão 350 ms, faixa 100–2000).
- **RF-05** Detectar desconexão (Bluetooth, suspensão) e recapturar o mouse em até 3 s após ele voltar, sem reiniciar o serviço.
- **RF-06** Recarregar a configuração sem reiniciar: via D-Bus (`Reload`) e ao detectar mudança no arquivo.
- **RF-07** Configuração inválida não derruba o daemon: mantém a última válida e publica o erro no campo `error` do status.
- **RF-08** Modo identificar: enquanto ativo, emitir um sinal D-Bus a cada gatilho, sem executar a ação.
- **RF-09** Listar mouses conectados (nome, caminho, barramento, se possui cada gatilho).
- **RF-10** Executar a ação de um gatilho sob demanda (`TestAction`) para o botão "Testar" da GUI.
- **RF-11** Ler a configuração no formato do protótipo (v1) e convertê-la para v2 na primeira gravação.

### Interface gráfica (`mousemap`)

- **RF-20** Mostrar os 4 gatilhos com a ação atual de cada um em texto legível ("Super + Page Up", "Comando: gnome-calculator").
- **RF-21** Editar a ação de um gatilho em um diálogo com: tipo de ação, ações prontas, captura de atalho, campo de comando e escolha de clique.
- **RF-22** Capturar um atalho pressionando as teclas no diálogo, inclusive combinações com Super, sem acionar o atalho do sistema.
- **RF-23** Aplicar ao salvar: gravar o TOML e chamar `Reload`; a mudança vale em menos de 1 s.
- **RF-24** Botão "Identificar": ao apertar um botão físico, destacar a linha correspondente.
- **RF-25** Botão "Testar" por gatilho.
- **RF-26** Escolher o mouse entre os listados pelo daemon.
- **RF-27** Ajustar o intervalo de repetição da inclinação.
- **RF-28** Mostrar o estado do serviço (ativo, aguardando mouse, sem permissão, erro de configuração, parado) com ação de correção: "Iniciar serviço", "Configurar permissões" (via `pkexec`), "Abrir arquivo de configuração".
- **RF-29** Opção "Iniciar com a sessão" (habilita/desabilita a unidade systemd de usuário).
- **RF-30** Restaurar padrões (todos os gatilhos em `default`), com confirmação.

### Futuro (fora do MVP)

- **RF-40** Perfis por aplicativo: mapeamento diferente conforme a janela em foco, informada por uma extensão do GNOME Shell via D-Bus.
- **RF-41** Macro: sequência de atalhos com intervalo.
- **RF-42** Vários mouses simultâneos, cada um com sua configuração.

## 4. Requisitos não funcionais

| Id | Requisito | Meta |
|---|---|---|
| RNF-01 | Latência adicionada ao movimento do mouse | < 1 ms no p99 |
| RNF-02 | CPU do daemon parado | ~0% (bloqueado em `poll`, sem timers ativos) |
| RNF-03 | Memória do daemon | < 40 MB RSS |
| RNF-04 | Recaptura após reconexão Bluetooth | ≤ 3 s |
| RNF-05 | Ambiente alvo | Fedora 44, GNOME 49+, Wayland; Python ≥ 3.12 |
| RNF-06 | Privilégios | Daemon e GUI rodam como usuário; root só na instalação |
| RNF-07 | Falha segura | Daemon encerrado ou travado não deixa o mouse inutilizado (o grab é liberado pelo kernel ao fechar o descritor; watchdog do systemd reinicia) |
| RNF-08 | Idioma | Interface em pt-BR via gettext (mensagens de origem em pt-BR) com tradução para en em `po/en.po` |
| RNF-09 | Acessibilidade | Navegável só por teclado; rótulos acessíveis em todos os controles |
| RNF-10 | Dependências | Somente pacotes do repositório Fedora: `python3-evdev`, `python3-gobject`, `gtk4`, `libadwaita` |
| RNF-11 | Logs | journald, sem registrar teclas emitidas nem comandos completos em nível info |

## 5. Arquitetura

São dois processos do usuário: o daemon, que lida com o mouse, e a GUI, que só edita a configuração e conversa com o daemon por D-Bus.

```
              ┌──────────────────────────── sessão do usuário ────────────────────────────┐
              │                                                                            │
 mouse físico │  ┌──────────────┐  D-Bus (sessão)   ┌───────────────────────────────┐     │
 /dev/input/  │  │  GUI          │ ───────────────▶ │  mousemapd (daemon)            │     │
 eventN ──────┼─▶│  mousemap     │ ◀─────────────── │  - captura exclusiva (grab)    │     │
   (grab)     │  │  GTK4/adw     │  sinais/status   │  - motor de remapeamento       │     │
              │  └──────┬───────┘                   │  - executor de ações           │     │
              │         │ grava                     └───┬───────────────┬───────────┘     │
              │         ▼                               │ lê            │ escreve          │
              │  ~/.config/mousemap/config.toml ◀───────┘               ▼                  │
              │                                         /dev/uinput: mouse virtual +        │
              │                                         teclado virtual ──▶ compositor      │
              └────────────────────────────────────────────────────────────────────────────┘
```

| Componente | Tecnologia | Responsabilidade |
|---|---|---|
| `mousemapd` | Python, python-evdev, GLib main loop, Gio D-Bus | Captura, remapeamento, ações, reconexão, API D-Bus |
| `mousemap` (GUI) | Python, PyGObject, GTK4, libadwaita | Editar configuração, mostrar estado, identificar/testar botões |
| `config.toml` | TOML v2 | Fonte única da configuração; editável à mão |
| `mousemap-setup` | shell, executado via `pkexec` | Regras udev, módulo uinput |
| Unidade systemd de usuário | `mousemapd.service` | Iniciar com a sessão, reiniciar em falha |

**Decisões**

- **Python + GTK4/libadwaita**: mesmo stack do protótipo; visual nativo do GNOME; tudo nos repositórios do Fedora.
- **GLib main loop no daemon**: o descritor do evdev entra no loop via `GLib.io_add_watch`, o mesmo loop atende o D-Bus. Sem threads.
- **D-Bus de sessão** em vez de socket próprio: introspecção, ativação e ferramentas (`busctl`, `d-spy`) de graça.
- **Arquivo como fonte da verdade**: a GUI não envia a configuração pelo D-Bus; grava o arquivo e pede `Reload`. Edição manual e GUI convivem.
- **Teclado virtual separado do mouse virtual**: o libinput classifica melhor dispositivos de um só tipo.

## 6. Modelo de configuração

Caminho: `$XDG_CONFIG_HOME/mousemap/config.toml` (padrão `~/.config/mousemap/config.toml`). Gravação atômica: arquivo temporário + `rename`.

### Esquema v2

```toml
version = 2

[settings]
tilt_cooldown_ms = 350          # 100–2000
device = "MX Anywhere 2S Mouse" # nome do evdev; vazio = primeiro mouse com botões laterais

[buttons]
tilt_left    = { keys = "super+Page_Up" }
tilt_right   = { keys = "super+Page_Down" }
side_back    = { cmd = "gnome-calculator" }
side_forward = "default"
```

| Ação | Forma | Validação |
|---|---|---|
| Padrão | `"default"` | — |
| Desativado | `"none"` | — |
| Atalho | `{ keys = "ctrl+shift+t" }` | Teclas separadas por `+`; cada uma é modificador (`ctrl`, `alt`, `altgr`, `shift`, `super`) ou nome `KEY_*` do kernel sem o prefixo, sem diferenciar maiúsculas e aceitando `_` (`Page_Up` = `PAGEUP`); no máximo 5 teclas |
| Comando | `{ cmd = "notify-send oi" }` | Texto não vazio; executado com `sh -c` |
| Clique | `{ click = "middle" }` | `left`, `right`, `middle`, `back`, `forward` |
| Ação pronta | `{ preset = "workspace-next" }` | Id do catálogo (abaixo); a GUI grava o preset para mostrar o nome amigável |

Gatilho ausente = `"default"`. Chaves desconhecidas geram aviso, não erro. Um erro em um gatilho invalida o arquivo todo (RF-07).

**Compatibilidade v1.** Sem `version`, os gatilhos ficam no nível raiz (formato do protótipo). O daemon lê os dois; a GUI grava sempre v2.

### Catálogo de ações prontas

| Id | Nome na GUI | Equivale a |
|---|---|---|
| `workspace-prev` / `workspace-next` | Área de trabalho anterior / seguinte | `super+Page_Up` / `super+Page_Down` |
| `overview` | Visão geral das atividades | `super` |
| `back` / `forward` | Voltar / Avançar | `alt+Left` / `alt+Right` |
| `copy` / `paste` | Copiar / Colar | `ctrl+c` / `ctrl+v` |
| `volume-up` / `volume-down` / `mute` | Volume + / − / mudo | `VolumeUp` / `VolumeDown` / `Mute` |
| `play-pause` / `next-track` / `prev-track` | Mídia | `PlayPause` / `NextSong` / `PreviousSong` |
| `close-tab` / `new-tab` | Fechar / nova aba | `ctrl+w` / `ctrl+t` |
| `screenshot` | Captura de tela | `Print` |

## 7. Interface gráfica

App GTK4/libadwaita, uma janela, id `io.github.mousemap`. Tudo cabe em uma tela; o único diálogo é o de editar ação.

### Janela principal

```
┌─ mousemap ─────────────────────────────────────────────── [≡] ─┐
│ ┌─ banner (só quando há problema) ───────────────────────────┐ │
│ │ ⚠ Sem permissão para acessar o mouse.  [Configurar]        │ │
│ └────────────────────────────────────────────────────────────┘ │
│  Mouse                                                         │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ MX Anywhere 2S  •  Bluetooth  •  Ativo          [ ▾ ]     │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  Botões                                   [ Identificar botão ]│
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Roda para a esquerda    Área de trabalho anterior  ▶ [⟳] │ │
│  │ Roda para a direita     Área de trabalho seguinte  ▶ [⟳] │ │
│  │ Lateral de trás         Comando: gnome-calculator  ▶ [⟳] │ │
│  │ Lateral da frente       Padrão                     ▶ [⟳] │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  Ajustes                                                       │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Repetição da inclinação      ──●────────  350 ms         │ │
│  │ Iniciar com a sessão                              [ ●]   │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
  [⟳] = Testar      [≡] = menu: Restaurar padrões, Abrir config, Sobre
```

Componentes: `AdwApplicationWindow`, `AdwBanner` (estado), `AdwPreferencesGroup` com `AdwComboRow` (mouse), `AdwActionRow` por gatilho (título, subtítulo com a ação, botão Testar, seta para editar), `AdwSpinRow` (repetição) e `AdwSwitchRow` (iniciar com a sessão).

### Diálogo "Editar ação"

```
┌─ Lateral de trás ─────────────────────── [Cancelar] [Salvar] ┐
│  Tipo de ação                                                 │
│   ( ) Padrão   ( ) Desativado   (•) Ação pronta               │
│   ( ) Atalho de teclado   ( ) Comando   ( ) Outro clique      │
│                                                               │
│  Ação pronta: [ Volume +                              ▾ ]     │
│  ── ou ─ Atalho: [ Pressione as teclas…  Ctrl + Shift + T ]   │
│  ── ou ─ Comando: [ gnome-calculator           ] [Escolher…]  │
│  ── ou ─ Clique:  [ Clique do meio             ▾ ]            │
└───────────────────────────────────────────────────────────────┘
```

`AdwDialog` com `AdwToolbarView`. Só aparece o campo do tipo escolhido. "Salvar" fica desativado enquanto o campo for inválido.

**Captura de atalho (RF-22).** Um `Gtk.EventControllerKey` em fase de captura recebe as teclas. Os atalhos do sistema são inibidos durante a captura com `Gtk.Window.set_inhibit_system_shortcuts` / `GdkToplevel.inhibit_system_shortcuts`. O código físico (`keycode − 8` = código evdev) é convertido para o nome `KEY_*`. Assim o atalho gravado é o que o daemon emite, independentemente do layout (ABNT2 ou US). Esc cancela; Backspace sozinho limpa.

### Fluxos

1. **Primeira execução.** A GUI abre, chama `GetStatus`. Se o serviço não responde: banner "Serviço parado" com [Iniciar] (`systemctl --user enable --now`). Se `no_permission`: banner com [Configurar] → `pkexec mousemap-setup` → nova consulta.
2. **Editar.** Clicar na linha → diálogo → Salvar → grava o TOML → `Reload` → subtítulo da linha atualizado; toast "Aplicado".
3. **Identificar.** [Identificar botão] liga `SetLearnMode(true)`; a cada sinal `TriggerPressed` a linha correspondente pisca e ganha foco; termina em 10 s ou ao clicar de novo.
4. **Testar.** [⟳] chama `TestAction(gatilho)`.
5. **Trocar mouse.** O combo lista `ListDevices`; a escolha grava `settings.device` e dá `Reload`.

### Estados e mensagens

| Status do daemon | Banner | Ação oferecida |
|---|---|---|
| `running` | — | — |
| `waiting_device` | "Mouse desconectado. Ligue-o ou escolha outro." | — |
| `no_permission` | "Sem permissão para acessar o mouse." | Configurar (pkexec) |
| `error` preenchido | "Erro na configuração: <mensagem>" | Restaurar padrões |
| serviço ausente | "O serviço do mousemap não está rodando." | Iniciar |

## 8. Daemon

### Ciclo de vida

```
 iniciar ─▶ carregar config ─┬─ erro ─▶ error preenchido (usa padrões) ┐
                             └─ ok ───────────────────────────────┐ │
                                                                  ▼ ▼
           ┌──────────────────────────────────────────▶ waiting_device ◀─────────┐
           │                         mouse aparece (udev ou varredura 2 s)       │
           │                                       ▼                              │
           │                            abrir + grab + criar uinput               │
           │                         PermissionError ▼        ok ▼                │
           │                              no_permission       running ── ENODEV ──┘
           │                                                    │
           └────────────── Reload / troca de device ◀───────────┘
```

- **Detecção de dispositivo.** Pelo sysfs (`/sys/class/input`, sem exigir permissão), com nova varredura a cada 2 s fora do estado `running`. Os dispositivos virtuais do próprio mousemap (nome começando com "mousemap") nunca são candidatos.
- **Encaminhamento.** Todo evento não interceptado vai para o mouse virtual sem alteração, inclusive `EV_MSC`, `SYN_REPORT` e rolagem de alta resolução.
- **Inclinação.** Cada passo da inclinação gera `REL_HWHEEL` (±1) e `REL_HWHEEL_HI_RES` (±120). Os dois são descartados quando o gatilho está mapeado; a ação dispara só no `REL_HWHEEL` e respeita o intervalo de repetição.
- **Botões com atalho.** Pressionar o botão pressiona as teclas na ordem; soltar libera na ordem inversa. Se o mouse desconectar com teclas pressionadas, o daemon libera todas (evita Ctrl "preso").
- **Comandos.** `subprocess.Popen(..., start_new_session=True)`, saída descartada, `SIGCHLD` ignorado para não deixar zumbis.
- **Recarga.** Gatilhos novos valem imediatamente. Se o teclado virtual precisar de teclas novas, ele é recriado (a capacidade do uinput é fixada na criação). Troca de device fecha e reabre a captura.
- **Encerramento.** `SIGTERM`: libera teclas pressionadas, solta o grab, destrói os dispositivos virtuais.
- **Watchdog.** `Type=notify` + `WatchdogSec=10`; o loop envia `WATCHDOG=1` a cada 5 s.

### API D-Bus

Nome `io.github.mousemap.Daemon`, objeto `/io/github/mousemap`, interface `io.github.mousemap.Daemon1`.

| Membro | Tipo | Assinatura | Descrição |
|---|---|---|---|
| `GetStatus` | método | `() → a{sv}` | `state` (s: running, waiting_device, no_permission), `device` (s), `path` (s), `error` (s, erro de configuração), `config_path` (s), `learning` (b) |
| `Reload` | método | `() → (b, s)` | Relê a config; retorna sucesso e mensagem de erro |
| `ListDevices` | método | `() → aa{sv}` | `name`, `path`, `bus` (usb/bluetooth/…), `triggers` (as), `accessible` (b) |
| `SetLearnMode` | método | `(b) → ()` | Liga/desliga o modo identificar; desliga sozinho após 10 s |
| `TestAction` | método | `(s) → (b, s)` | Executa a ação do gatilho informado |
| `StatusChanged` | sinal | `a{sv}` | Mesmo conteúdo de `GetStatus` |
| `TriggerPressed` | sinal | `s` | Só no modo identificar; nome do gatilho |
| `Version` | propriedade | `s` | Versão do daemon |

## 9. Permissões, instalação e empacotamento

O daemon precisa ler o mouse (`/dev/input/eventN`) e escrever em `/dev/uinput`. Isso é concedido ao usuário da sessão ativa pela tag `uaccess` do systemd-logind, sem grupo `input` e sem novo login.

```
# /usr/lib/udev/rules.d/70-mousemap.rules  (antes do 73-seat-late.rules)
KERNEL=="uinput", SUBSYSTEM=="misc", OPTIONS+="static_node=uinput", TAG+="uaccess"
SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_MOUSE}=="1", TAG+="uaccess"
```

- A segunda regra vale só para nós classificados como mouse, nunca para teclados (evita leitura de digitação).
- `/etc/modules-load.d/mousemap.conf` com `uinput`.

**Segurança.** Acesso ao uinput permite que processos do usuário injetem entrada. É o mesmo modelo usado por Steam e input-remapper e aceitável em desktop de um usuário; fica registrado na documentação. Comandos (`cmd`) rodam como o usuário e vêm só do arquivo dele.

### Layout instalado (RPM)

| Caminho | Conteúdo |
|---|---|
| `/usr/bin/mousemapd` | Daemon |
| `/usr/bin/mousemap` | GUI |
| `/usr/libexec/mousemap-setup` | Ajustes de permissão (para instalação manual/pkexec) |
| `/usr/share/polkit-1/actions/io.github.mousemap.policy` | Ação polkit do setup |
| `/usr/lib/udev/rules.d/70-mousemap.rules` | Regras acima |
| `/usr/lib/modules-load.d/mousemap.conf` | `uinput` |
| `/usr/lib/systemd/user/mousemapd.service` | Unidade de usuário |
| `/usr/share/dbus-1/services/io.github.mousemap.Daemon.service` | Ativação D-Bus (`SystemdService=mousemapd.service`) |
| `/usr/share/applications/io.github.mousemap.desktop` | Atalho no menu |
| `/usr/share/metainfo/io.github.mousemap.metainfo.xml` | Metadados (GNOME Software) |
| `/usr/share/icons/hicolor/scalable/apps/io.github.mousemap.svg` | Ícone |
| `/usr/share/locale/*/LC_MESSAGES/mousemap.mo` | Traduções |

**Distribuição.** RPM via Copr (`dnf copr enable <usuario>/mousemap`). O `%post` recarrega as regras udev e carrega o uinput, então o pacote funciona sem `pkexec`. Flatpak não é adequado: o daemon precisa de udev/uinput no host.

**Desinstalar** remove a unidade, as regras e o módulo; a configuração do usuário permanece.

## 10. Estrutura do repositório

```
mousemap/
├── SPEC.md
├── README.md
├── pyproject.toml
├── meson.build                    # instala dados, traduções e arquivos de sistema
├── src/mousemap/
│   ├── __init__.py
│   ├── config.py                  # esquema, parse v1/v2, validação, gravação atômica
│   ├── keys.py                    # nomes ⇄ códigos evdev, formatação para a GUI
│   ├── presets.py                 # catálogo de ações prontas
│   ├── daemon/
│   │   ├── main.py                # entrada mousemapd, loop GLib, sinais
│   │   ├── device.py              # descoberta, grab, reconexão
│   │   ├── engine.py              # interceptação e ações (puro, testável)
│   │   └── dbus_service.py
│   └── gui/
│       ├── main.py                # entrada mousemap (Adw.Application)
│       ├── window.py              # interface montada em Python (sem .blp)
│       ├── action_dialog.py       # inclui a captura de atalho
│       └── daemon_client.py
├── data/                          # .desktop, metainfo, ícone, udev, systemd, dbus, polkit
├── po/                            # pt_BR.po, en.po
├── packaging/mousemap.spec        # RPM
└── tests/
```

## 11. Testes e critérios de aceitação

### Testes automatizados

| Nível | O que cobre | Como |
|---|---|---|
| Unidade | Parse v1/v2, validação, nomes de tecla, catálogo | unittest (roda também com pytest), sem hardware |
| Unidade | `engine`: interceptação, ordem de teclas, intervalo de repetição, repasse | Dispositivos uinput falsos (como no protótipo) |
| Integração | Daemon real com mouse virtual de origem criado via uinput; conferir eventos no dispositivo de saída | pytest com `/dev/uinput` acessível (marcado `@hardware`, roda local) |
| D-Bus | Métodos e sinais | `dbus-run-session` + daemon em modo teste |
| GUI | Diálogo, validação, captura de atalho | Testes de widgets com GTK em modo offscreen |

Cobertura mínima: 85% em `config`, `keys` e `engine`.

### Critérios de aceitação do MVP

- [ ] Com o RPM instalado, abrir "mousemap" no menu e configurar os 4 gatilhos sem terminal.
- [ ] Cada ação (atalho, comando, clique, padrão, desativado, pronta) funciona em cada gatilho no GNOME/Wayland.
- [ ] Mudança salva vale em menos de 1 s, sem reiniciar nada.
- [ ] "Identificar botão" destaca a linha certa para os 4 gatilhos.
- [ ] Desligar e ligar o mouse: o remapeamento volta em até 3 s.
- [ ] Suspender e retomar o notebook: o remapeamento volta.
- [ ] `kill -9` no daemon: o mouse continua funcionando (sem remapeamento) e o systemd reinicia o serviço.
- [ ] Atalho mantido em botão lateral (ex.: `ctrl`) não fica preso após soltar ou desconectar.
- [ ] Configuração com erro mostra o banner e o daemon segue com a última configuração válida.
- [ ] Movimento e rolagem vertical sem diferença perceptível (RNF-01).
- [ ] Arquivo editado à mão é aceito e exibido corretamente na GUI.

## 12. Roadmap

| Marco | Entrega | Pronto quando |
|---|---|---|
| M0 Protótipo | CLI + TOML + systemd | Feito em 15/10/2026; substituído pelo M1 |
| M1 Daemon v2 | Pacote `src/mousemap`, config v2, GLib loop, D-Bus, reconexão, watchdog | Feito em 15/10/2026 (0.2.0); bug aberto: BUG-001 |
| M2 GUI MVP | Janela, diálogo, captura de atalho, identificar, testar, banners | Feito em 15/10/2026 (0.2.0) |
| M3 Empacotamento | meson, RPM, Copr, traduções pt-BR/en | Feito em 15/10/2026 (0.3.0): RPM gerado e instalado/removido num contêiner Fedora 44 limpo. Pendente: publicar no Copr e testar udev/polkit/systemd numa máquina real instalada pelo RPM |
| M4 Perfis por app | Extensão GNOME Shell + perfis na config e na GUI (§14) | Feito em 15/10/2026 (0.4.0); extensão testada com gjs e daemon real, falta validar dentro do GNOME Shell |
| M5 Extras | Macros, mais botões, vários mouses | Conforme demanda |

## 13. Riscos e questões em aberto

### Riscos

| Risco | Impacto | Mitigação |
|---|---|---|
| Solaar (ou firmware) deixa botões "desviados" via HID++ e eles não chegam ao evdev | Botão não responde | Detectar ausência de eventos no modo identificar e sugerir desligar/ligar o mouse; documentar conflito com Solaar/logiops |
| Outro mouse envia a inclinação como botão (`BTN_*`) em vez de `REL_HWHEEL` | Gatilho não reconhecido | `ListDevices` informa os gatilhos disponíveis; modo identificar revela o evento real; mapeamento por device no futuro |
| GNOME/Wayland não informa a janela em foco a apps comuns | Bloqueia perfis por app | Extensão do GNOME Shell (M4) |
| Atalhos do sistema disparam durante a captura na GUI | Captura errada | `inhibit_system_shortcuts`; fallback: digitar o atalho em texto |
| Mouse virtual aparece duplicado nas configurações do GNOME | Confusão do usuário | Nome claro ("mousemap: MX Anywhere 2S"); configurações de ponteiro do GNOME são globais |
| Permissão `uaccess` em todos os mouses | Superfície de segurança maior | Restrito a `ID_INPUT_MOUSE`; documentado |

### Questões em aberto

- Nome definitivo e id do app (`io.github.mousemap` supõe hospedagem no GitHub).
- Repositório: https://github.com/joseamttabreu/mousemap (privado). Para o Copr, precisa ser público.
- Suportar KDE Plasma já no MVP ou só testar depois?
- Quais ações padrão vêm de fábrica? (protótipo: áreas de trabalho na inclinação, voltar/avançar nas laterais)
- Publicar no Copr público ou manter só para uso interno?
- Incluir o botão abaixo da roda (troca do modo da roda) — exige HID++ e hoje fica fora.

## 14. M4 — Perfis por aplicativo

Cada aplicativo pode ter o próprio mapeamento; o que ele não define vem do padrão global. Quem informa o aplicativo em foco é uma extensão do GNOME Shell, porque no Wayland nenhum outro processo tem essa informação.

```
 GNOME Shell                        sessão do usuário
┌──────────────────────────┐  D-Bus   ┌──────────────────────────────────────┐
│ extensão mousemap        │ ───────▶ │ mousemapd                            │
│ foco mudou → id do app   │ SetActive│  ações = padrão global ⊕ perfil do app│
│ (Shell.WindowTracker)    │   App    │  ActiveAppChanged ──▶ GUI            │
└──────────────────────────┘          └──────────────────────────────────────┘
```

### Requisitos

- **RF-50** A extensão envia ao daemon o id do aplicativo em foco (id do `.desktop` sem a extensão, ex.: `org.mozilla.firefox`) e a classe da janela (`WM_CLASS`), a cada mudança de foco. Nunca envia o título da janela.
- **RF-51** A extensão reenvia o foco atual quando o daemon aparece no barramento (reinício, recarga) e envia vazio ao ser desativada.
- **RF-52** Perfil é escolhido por id do aplicativo ou, se não houver, pela classe da janela; sem diferenciar maiúsculas. Sem perfil correspondente, vale o padrão global.
- **RF-53** Gatilho ausente no perfil herda o padrão global; `"default"` no perfil significa explicitamente "comportamento original do mouse".
- **RF-54** A troca de perfil no meio de um clique não prende nada: a soltura usa a ação vigente no aperto (mesma regra da recarga).
- **RF-55** A GUI lista os perfis, adiciona um perfil escolhendo entre os aplicativos instalados (ou digitando o id), remove perfis e edita cada gatilho com a opção extra "Igual ao padrão".
- **RF-56** A GUI mostra se a extensão está ativa e oferece ativá-la; sem a extensão, os perfis ficam salvos mas não são aplicados.
- **RF-57** "Testar" em um perfil executa a ação daquele perfil, independentemente do aplicativo em foco.

### Configuração

Tabela opcional `[apps."<id>"]`, compatível com a versão 2 (daemons antigos ignoram com aviso):

```toml
[apps."org.mozilla.firefox"]
name = "Firefox"                      # rótulo na GUI (opcional)
tilt_left  = { keys = "ctrl+shift+TAB" }
tilt_right = { keys = "ctrl+TAB" }
# side_back e side_forward ausentes: herdam [buttons]
```

### D-Bus (acréscimos)

| Membro | Tipo | Assinatura | Descrição |
|---|---|---|---|
| `SetActiveApp` | método | `(s app_id, s wm_class) → ()` | Chamado pela extensão; vazios = sem foco |
| `TestProfileAction` | método | `(s app_id, s trigger) → (b, s)` | Executa a ação do gatilho naquele perfil |
| `ActiveAppChanged` | sinal | `(s app_id, s profile)` | `profile` vazio = padrão global |
| `GetStatus` | — | — | ganha `app` (s), `profile` (s) e `focus_source` (b: a extensão já informou o foco) |

### Extensão

- UUID `mousemap@joseamttabreu.github.com`, GNOME Shell 50, módulo ES, sem preferências.
- Instalada em `/usr/share/gnome-shell/extensions/` pelo RPM e em `~/.local/share/gnome-shell/extensions/` pelo `install-dev.sh`. No Wayland, extensão nova só é detectada após sair e entrar na sessão.
- Chamada D-Bus assíncrona e sem ativação automática (`NO_AUTO_START`): foco não deve iniciar o daemon.
