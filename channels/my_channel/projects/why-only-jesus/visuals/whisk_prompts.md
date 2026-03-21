# Whisk 이미지 프롬프트 — Why Only Jesus

아래 프롬프트를 Whisk (labs.google/whisk)에 하나씩 입력하세요.
생성된 이미지를 `scene_001.png` ~ `scene_020.png`로 저장하면 됩니다.
모든 이미지: 16:9, 텍스트 없음, 시네마틱 디지털 아트

---

## Scene 01 — 인트로 (질문을 던지다)
파일명: `scene_001.png`
```
A lone figure standing at a crossroads of multiple glowing paths in a vast dark landscape, each path leading to a different ornate temple gate, dramatic fog, cinematic golden hour lighting, wide 16:9, digital art, no text
```

## Scene 02 — 죄의 원어 (과녁을 빗나감)
파일명: `scene_002.png`
```
An ancient archer's arrow missing a glowing golden target in a dark void, the arrow trail curving away, Hebrew letters faintly visible in the background, dramatic lighting, cinematic digital art, 16:9, no text
```

## Scene 03 — 하나님의 형상 (과녁)
파일명: `scene_003.png`
```
A majestic golden statue of a human figure radiating warm light, standing in an ancient temple, divine light pouring down from above, symbolizing the image of God, cinematic, 16:9 wide, digital art, no text
```

## Scene 04 — 창세기 3장 (선악과)
파일명: `scene_004.png`
```
A luminous forbidden fruit hanging from a dark twisted tree, a serpent coiled around the branch, Garden of Eden in the background with fading light, dramatic shadows, cinematic digital art, 16:9, no text
```

## Scene 05 — 죽음의 공포 (죄의 뿌리)
파일명: `scene_005.png`
```
A terrified human figure crouching in darkness, surrounded by swirling dark shadows shaped like chains and skulls, a faint heartbeat glow in the chest area, fear and isolation, cinematic dark atmosphere, 16:9, no text
```

## Scene 06 — 요한일서 (사랑 vs 두려움)
파일명: `scene_006.png`
```
A split composition: left side is warm golden light with an open embrace, right side is cold blue darkness with a figure curled up in fear, the two sides meeting in the middle with dramatic contrast, 16:9 wide, digital art, no text
```

## Scene 07 — 닫힌 순환 (탈출 불가)
파일명: `scene_007.png`
```
A person trapped inside a massive circular loop made of dark chains floating in a void, the loop connects death skull to broken heart to chains back to skull, infinite cycle, dramatic dark cinematic lighting, 16:9, no text
```

## Scene 08 — 대속의 원어 (카파르 = 덮다)
파일명: `scene_008.png`
```
Noah's Ark being coated with dark pitch (bitumen) by workers, close-up of hands applying the protective covering, water threatening outside, warm interior light, ancient biblical scene, cinematic, 16:9, no text
```

## Scene 09 — 형벌 대속 vs 해방 대속
파일명: `scene_009.png`
```
Split image: left side shows a courtroom with a judge's gavel striking down, right side shows a father paying gold coins to free his child from chains in a slave market, dramatic lighting contrast, 16:9 wide, digital art, no text
```

## Scene 10 — 이사야 53장
파일명: `scene_010.png`
```
An ancient Hebrew scroll unrolling with glowing text, a gentle hand guiding a lost sheep back to the flock, pastoral biblical landscape, warm golden sunset, cinematic, 16:9 wide, digital art, no text
```

## Scene 11 — 다른 종교의 한계
파일명: `scene_011.png`
```
Multiple people drowning in dark water, each trying to teach the others how to swim but all sinking together, one distant shore with a lighthouse beam, dramatic stormy ocean scene, cinematic, 16:9, no text
```

## Scene 12 — 예수님만 가능한 이유 (성육신)
파일명: `scene_012.png`
```
A divine figure of pure light diving down from heaven into dark churning waters to rescue a drowning person, dramatic splash, golden light piercing through darkness, cinematic biblical art, 16:9 wide, no text
```

## Scene 13 — 부활 (2000년 전)
파일명: `scene_013.png`
```
An empty ancient stone tomb with the massive stone rolled away, brilliant golden sunrise light flooding through the entrance, burial cloths left behind, cinematic Easter morning scene, 16:9 wide, digital art, no text
```

## Scene 14 — 성령의 원어 (루아흐 = 숨)
파일명: `scene_014.png`
```
God's breath as a luminous golden wind flowing into a clay human figure, the figure gradually coming to life with warm light spreading through its body, ancient creation scene, cinematic, 16:9 wide, digital art, no text
```

## Scene 15 — 성령과 부활의 연결
파일명: `scene_015.png`
```
A massive dam breaking apart with brilliant golden water flooding through into a dry barren landscape, the water bringing life and green wherever it flows, dramatic cinematic wide shot, 16:9, digital art, no text
```

## Scene 16 — 성령의 구체적 역할
파일명: `scene_016.png`
```
A glowing warm light residing inside a human chest (heart area), radiating outward through the whole body, transforming darkness into golden warmth, the person's posture shifting from fear to confidence, cinematic, 16:9, no text
```

## Scene 17 — 디모데후서 요약
파일명: `scene_017.png`
```
Three symbols floating in brilliant light: a lightning bolt (power), a radiant heart (love), and a balanced scale (sound mind), replacing dark fearful shadows that dissolve away, cinematic divine atmosphere, 16:9, digital art, no text
```

## Scene 18 — 생수의 강 (요한복음 7장)
파일명: `scene_018.png`
```
Rivers of crystal clear living water flowing from within a person's body outward into a dry desert landscape, transforming it into lush paradise, golden sunlight, cinematic wide biblical scene, 16:9, digital art, no text
```

## Scene 19 — 결론 (길, 진리, 생명)
파일명: `scene_019.png`
```
A single glowing ancient doorway standing in vast darkness, brilliant warm light streaming through it, a narrow path leading to it, silhouettes of people walking toward the door with hope, cinematic biblical art, 16:9 wide, no text
```

## Scene 20 — 아웃트로 (참고 구절)
파일명: `scene_020.png`
```
An open ancient Bible with pages glowing with golden light, Hebrew and Greek letters floating upward like particles of light, peaceful library atmosphere, warm cinematic lighting, 16:9 wide, digital art, no text
```

---

## 이미지 저장 후 실행할 명령어

모든 이미지를 저장한 후 아래 명령으로 CapCut 비디오 트랙을 자동 추가합니다:

```bash
PYTHONIOENCODING=utf-8 py scripts/capcut_project.py channels/my_channel/projects/why-only-jesus/audio.mp3 channels/my_channel/projects/why-only-jesus/subtitle.srt "why-only-jesus" --aspect-ratio 16:9 --scenes-dir channels/my_channel/projects/why-only-jesus/visuals
```
