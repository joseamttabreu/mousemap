# Bugs conhecidos

| Id | Título | Severidade | Status | Aberto em |
|---|---|---|---|---|
| BUG-001 | Inclinar a roda para a esquerda é identificado como "Lateral da frente" | Alta | Fechado (causa externa: reprogramação do Solaar) | 15/10/2026 |

---

## BUG-001 — Inclinar a roda para a esquerda é identificado como "Lateral da frente"

**Severidade:** alta. Se o gatilho é reconhecido errado, a ação errada é executada: a ação de `side_forward` dispara ao inclinar para a esquerda, e o mapeamento de `tilt_left` nunca é usado.

**Ambiente**

- mousemap 0.2.0 (M1 + M2), instalado com `tools/install-dev.sh`
- Logitech MX Anywhere 2S via Bluetooth (`046d:b01a`), nó `/dev/input/event24`
- Fedora 44, kernel 7.2.10-200.fc44, GNOME/Wayland, python3-evdev 1.9.3
- Configuração: nenhuma (`~/.config/mousemap/config.toml` não existe; todos os botões em "Padrão")

**Passos para reproduzir**

1. Abrir o mousemap e clicar em "Identificar botão".
2. Inclinar a roda do mouse para a esquerda.

**Esperado:** a linha "Roda para a esquerda" é destacada (`TriggerPressed("tilt_left")`).
**Obtido:** a linha "Lateral da frente" é destacada.

**Ainda não verificado:** se a inclinação para a direita e as duas laterais são identificadas corretamente.

**Análise inicial**

O motor só emite `side_forward` ao receber `EV_KEY BTN_EXTRA` (`src/mousemap/daemon/engine.py`, `BUTTON_TRIGGERS`), e `tilt_left` ao receber `REL_HWHEEL` negativo. Logo, o mouse provavelmente está enviando `BTN_EXTRA` ao inclinar para a esquerda. Hipóteses:

1. **O descritor HID do mouse mapeia a inclinação como botão.** O nó declara 16 botões (`BTN_LEFT`…`0x11f`), comum em mouses Logitech. A inclinação pode chegar como botão HID 5 (`BTN_EXTRA`) e as laterais como outros botões (`BTN_FORWARD`/`BTN_BACK`), que o motor hoje não trata.
2. **A inclinação gera os dois eventos** (`REL_HWHEEL` e um botão). No modo identificar, a GUI destaca o último sinal recebido.
3. **Firmware em estado "desviado" pelo Solaar** (que estava rodando antes): botões reprogramados via HID++ continuam assim até o mouse ser desligado.

**Captura de 15/10/2026 (`python3 -m evdev.evtest`, roda inclinada para os dois lados e as duas laterais apertadas)**

| Evento | Vezes | Código HID |
|---|---|---|
| `BTN_SIDE` | 5 | botão 4 (`MSC_SCAN 0x90004`) |
| `BTN_EXTRA` | 1 | botão 5 (`MSC_SCAN 0x90005`) |
| `REL_HWHEEL +1` (+ `REL_HWHEEL_HI_RES +120`) | 2 | rolagem horizontal |
| `REL_HWHEEL −1` | 0 | — |

Conclusões:

- **Confirmado:** a inclinação para a esquerda não gera `REL_HWHEEL` negativo. O gatilho `tilt_left`, como implementado, nunca é reconhecido neste mouse.
- **Confirmado:** a inclinação para a esquerda chega como `BTN_SIDE` ou `BTN_EXTRA`, colidindo com uma lateral. A captura não permite dizer qual, porque a ordem das ações não foi registrada.
- **Mais provável agora:** hipótese 3. O MX Anywhere 2S, sem reprogramação, envia rolagem horizontal para os dois lados; uma inclinação virar botão HID indica controle reprogramado via HID++ (Solaar), que só volta ao normal quando o mouse é desligado.

**Diagnóstico guiado**

```bash
mousemapd --diagnose    # pede uma ação por vez e compara com o esperado; para e reinicia o serviço sozinho
```

Rodar duas vezes: como está, e depois de desligar e ligar o mouse pela chave (descarta ou confirma a hipótese 3).

**Diagnóstico guiado de 15/10/2026 — tudo OK**

```
Roda para a esquerda   OK (REL_HWHEEL −)
Roda para a direita    OK (REL_HWHEEL +)
Lateral de trás        OK (BTN_SIDE)
Lateral da frente      OK (BTN_EXTRA)
```

O mesmo mouse que antes mandava a inclinação à esquerda como botão agora manda `REL_HWHEEL −`, exatamente o que o motor espera. O estado do mouse mudou entre as medições, o que confirma a hipótese 3: reprogramação via HID++ deixada pelo Solaar, desfeita quando o mouse desliga ou reconecta. **Não há defeito no código do mousemap.**

Para fechar:

- [x] Confirmado na GUI ("Identificar botão") em 15/10/2026: "Roda para a esquerda" é destacada corretamente. **Bug fechado.**
- [ ] Se voltar a acontecer: rodar `mousemapd --diagnose` antes de desligar o mouse e registrar aqui se o Solaar (ou logiops) foi executado.

Melhoria futura (não bloqueia): o daemon pode avisar quando um gatilho chega com um código diferente do esperado, por exemplo `tilt_left` ausente e botões HID extras aparecendo.

**Diagnóstico (eventos brutos)**

```bash
systemctl --user stop mousemapd          # o serviço captura o mouse com exclusividade
python3 -m evdev.evtest /dev/input/event24
# incline para a esquerda, para a direita, aperte a lateral de trás e a da frente; Ctrl+C
systemctl --user start mousemapd
```

Repetir após desligar e ligar o mouse (descarta a hipótese 3).

**Correção provável**

Tornar o mapeamento físico → gatilho configurável por dispositivo, em vez de fixo em `BTN_SIDE`/`BTN_EXTRA`/`REL_HWHEEL`:

- tabela de perfis conhecidos (ex.: MX Anywhere 2S);
- botão "Identificar" gravando o código evdev real de cada gatilho em `[devices."<nome>"]` na configuração.

Incluir um teste de regressão no `tests/test_engine.py` com a sequência de eventos capturada.
