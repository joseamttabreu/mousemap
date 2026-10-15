# mousemap

Escolha o que cada botão extra do mouse faz no Linux (GNOME/Wayland), por uma interface gráfica.
Feito para o Logitech MX Anywhere 2S, mas funciona com qualquer mouse que tenha botões laterais
ou roda com inclinação. Especificação completa em [SPEC.md](SPEC.md); bugs conhecidos em [BUGS.md](BUGS.md).

| Botão | Exemplos de ação |
|---|---|
| Roda para a esquerda / direita | trocar de área de trabalho, volume, atalho, comando |
| Laterais (trás / frente) | voltar/avançar, copiar/colar, clique do meio, abrir um programa |

## Instalação (desenvolvimento)

```bash
sudo bash tools/setup-system.sh   # uma vez: dependências + permissões (udev/uinput)
bash tools/install-dev.sh          # serviço do usuário, atalho no menu, comandos em ~/.local/bin
```

Depois abra **mousemap** no menu de aplicativos. Para remover: `bash tools/install-dev.sh --uninstall`.

## Pacote RPM

```bash
sudo dnf install rpm-build meson python3-devel systemd-rpm-macros appstream desktop-file-utils
bash tools/make-srpm.sh                       # gera build/rpm/mousemap-<versão>-1.src.rpm
rpmbuild --rebuild build/rpm/mousemap-*.src.rpm
```

No Copr, crie o projeto apontando para o repositório git com o método **make_srpm** (usa `.copr/Makefile`).

Build e testes sem gerar pacote: `meson setup build && meson test -C build`.

## Traduções

As mensagens de origem estão em português (pt-BR); `po/en.po` traz o inglês. Ao mudar textos:

```bash
xgettext --from-code=UTF-8 -L Python -k_ -f po/POTFILES -o po/mousemap.pot
msgmerge -U po/en.po po/mousemap.pot
```

## Uso pelo terminal

```bash
mousemapd --list     # mouses detectados e botões extras de cada um
mousemapd --check    # valida ~/.config/mousemap/config.toml
journalctl --user -u mousemapd -f
```

A configuração também pode ser editada à mão (`~/.config/mousemap/config.toml`); o serviço recarrega sozinho ao salvar.

```toml
version = 2

[settings]
device = "MX Anywhere 2S Mouse"   # vazio = automático
tilt_cooldown_ms = 350

[buttons]
tilt_left    = { preset = "workspace-prev" }
tilt_right   = { preset = "workspace-next" }
side_back    = { keys = "ctrl+c" }
side_forward = { cmd = "gnome-calculator" }
```

## Como funciona

O serviço `mousemapd` captura o mouse com exclusividade (evdev), reemite tudo por um mouse virtual
(uinput) e troca apenas os botões configurados por atalhos, comandos ou outros cliques. A interface
`mousemap` (GTK4/libadwaita) edita o arquivo e conversa com o serviço por D-Bus.

Se o serviço parar, o kernel devolve o mouse ao comportamento normal.

## Testes

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .   # ou: meson test -C build
```

## Problemas conhecidos

- **Solaar ou logiops** rodando ao mesmo tempo podem "desviar" botões; feche-os. Se um botão lateral
  não aparecer em "Identificar botão", desligue e ligue o mouse.
- Ao gravar um atalho com a tecla Super, o GNOME pode pedir permissão para o app inibir atalhos do sistema.
