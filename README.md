# Robô de cortes

Vigia canais do YouTube (padrão: **GameplayRJ** em português e **IShowSpeed** em inglês, com versão extra legendada em português, só lives com "GTA" no título) e grava até 2 lives ao mesmo tempo (os cortes são montados um por vez, para não pesar a VPS). Quando a live abre, grava em pedaços curtos, lê o chat e mede o volume do áudio. Quando o chat explode ("KKKK", "clipa", muita mensagem de uma vez) ou o volume dispara, ele:

1. Pega ~1 minuto ao redor do momento
2. Manda o áudio + o chat para o Gemini, que dá uma nota e escreve título, gancho e legendas
   (o corte começa 5s antes do pico do chat e termina na primeira pausa do streamer depois dele)
3. Monta o vídeo vertical (720x1280): se a IA achar a webcam do streamer, fica **webcam em cima e gameplay embaixo**;
   sem webcam, a tela inteira no meio (nada cortado), com gancho e legenda
4. Manda para o seu WhatsApp pelo **assistente-wpp**

Você responde no WhatsApp:

| Mensagem | O que faz |
|---|---|
| `ok 12` | Aprova e manda o título + descrição prontos para copiar |
| `não 12` | Descarta e apaga |
| `postei 12` | Apaga da VPS (você já postou) |
| `cortes` | Mostra se está gravando e os cortes pendentes |
| `corte agora` | Corta o último minuto da live na hora (sem esperar pico, sem filtro de nota) |
| `limpar cortes` | Apaga todos os cortes da VPS e zera o contador (pede `confirmar limpeza`) |
| `diag` | Diagnóstico da live: gravação, chat, volume e cortes |
| `log` | Últimas linhas do log do robô |

Também dá para **responder ao vídeo** só com `ok`, `não` ou `postei`, sem o número.

O disco não enche: só os últimos 15 min da live ficam guardados, e corte sem resposta é apagado em 24h.

## Instalar na VPS

Pré-requisito: o **assistente-wpp** atualizado e rodando (ele cria a rede `robos` que os dois usam).

```bash
cd ~ && git clone git@github-cortes:RyanMachadoSilva/robo-cortes.git
cd robo-cortes
cp .env.example .env
nano .env          # GEMINI_API_KEY (de um projeto novo) e TOKEN_ROBO
cp ~/cookies.txt config/cookies.txt
docker compose up -d --build
docker compose logs -f
```

O `TOKEN_ROBO` tem que ser **igual** no `.env` do robô e no `.env` do assistente (gere com `openssl rand -hex 16`). Depois de colocar no assistente: `cd ~/assistente-wpp && docker compose up -d --force-recreate`.

## Cookies do YouTube

O YouTube bloqueia muito IP de servidor ("confirme que você não é um robô"). Os cookies de uma **conta secundária** resolvem:

1. No Chrome, entre no YouTube com a conta secundária
2. Extensão **Get cookies.txt LOCALLY** → exportar com o youtube.com aberto
3. `scp cookies.txt ryan@IP_DA_VPS:~/robo-cortes/config/cookies.txt`
4. `docker compose restart`

Se os cookies vencerem, o robô avisa no WhatsApp.

## Ajustes (no .env)

| Variável | Padrão | Para quê |
|---|---|---|
| `INICIO_ANTES_PICO_S` | 5 | O corte começa X s antes do pico do chat. Começando atrasado? Suba para 8 ou 10 |
| `MIN_DEPOIS_PICO_S` | 6 | O fim (primeira pausa do streamer) só vale depois de X s do pico |
| `LEGENDA_TAMANHO` | 14 | Tamanho da legenda (maior = 16, menor = 12) |
| `LEGENDA_ALTURA` | 0.11 | Distância da legenda até o rodapé (0.15 = mais alto, 0.08 = mais baixo) |
| `NOTA_MINIMA` | 6 | Nota mínima da IA para o corte chegar em você. Muito corte ruim? Suba. Pouco corte? Desça |
| `MIN_ENTRE_CORTES_S` | 600 | No máximo 1 corte a cada 10 min |
| `CHAT_MULTIPLICADOR` / `CHAT_MIN_MSGS` | 3 / 10 | Sensibilidade ao chat |
| `PALAVRAS_MIN` | 5 | Quantas mensagens com "kkkk", "clipa", "mds" em 10s disparam |
| `VERSAO_EN` | nao | Para canais em português: `separado` manda também um vídeo em inglês, `junto` põe as duas legendas no mesmo vídeo |
| `CANAIS` | @gameplayrj:pt,@IShowSpeed:en+pt | Canais e idioma do corte (`pt`, `en`). `en+pt` manda também uma versão com legenda em português; `pt+en`, uma em inglês |
| `SO_TITULO_COM` | gta | Só grava lives com essa palavra no título (vazio = todas) |
| `MAX_LIVES` | 2 | Quantas lives gravar ao mesmo tempo (KVM 1: 2; KVM 2: 4) |

Depois de mudar: `docker compose up -d --force-recreate`.

## Comandos úteis

| O que | Comando |
|---|---|
| Ver o que está acontecendo | `docker compose logs -f` |
| Reiniciar | `docker compose restart` |
| Atualizar | `bash scripts/deploy.sh` |
| YouTube mudou e parou de gravar | `docker compose build --no-cache && docker compose up -d` (atualiza o yt-dlp) |

## O que aparece no log

- `vigiando ... a cada 90s`: esperando alguma live abrir
- `🔴 live aberta`: começou a gravar
- `⚡ momento detectado`: o chat explodiu, vai analisar
- `descartado pela IA (nota 4)`: a IA achou fraco
- `corte renderizado em 95s`: pronto, indo para o WhatsApp
- `YouTube bloqueou`: renove os cookies
