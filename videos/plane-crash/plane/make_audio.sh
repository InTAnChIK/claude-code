#!/usr/bin/env bash
# Synthesizes the background soundtrack (engine rumble, alarm, impact, timer ticks) into audio.wav.
set -euo pipefail
cd "$(dirname "$0")"
ffmpeg -v error -y \
 -f lavfi -i "anoisesrc=c=brown:a=0.7:d=80:r=44100" \
 -f lavfi -i "aevalsrc='0.10*sin(2*PI*880*t)*lt(t,4)*lt(mod(t*3,2),1)*lt(mod(t*3,1),0.6) + 0.9*gte(t,44)*exp(-(t-44)*2.5)*sin(2*PI*(55-30*min(t-44,1))*(t-44)) + 0.06*gte(t,44.5)*sin(2*PI*49*t)*(0.6+0.4*sin(2*PI*0.25*t)) + 0.22*gte(t,49)*lt(t,78)*lt(mod(t-49,1),0.025)*sin(2*PI*1600*t) + 0.25*gte(t,26)*lt(t,26.6)*sin(2*PI*1200*t)*lt(mod(t*8,1),0.5)':s=44100:d=80" \
 -filter_complex "[0]lowpass=f=260,volume='if(lt(t,44),0.9,if(lt(t,44.4),2.5*exp(-(t-44)*4),0.05))':eval=frame[n];[n][1]amix=inputs=2:normalize=0,afade=t=in:d=0.3,afade=t=out:st=78.5:d=1.5,alimiter=limit=0.9[a]" \
 -map "[a]" -ac 2 audio.wav
