# YouTube Auto - 유튜브 영상 자동 제작 파이프라인

## 프로젝트 개요
대본 작성 → TTS 음성 생성 → Whisper 자막 생성 → Whisk 이미지 + ffmpeg 모션 영상 → CapCut 프로젝트 생성을 자동화하는 도구.
"영상 만들어줘" 한 번이면 **롱폼(16:9) + 숏츠(9:16)** 두 가지가 동시에 생성된다.

## 대본 생성 워크플로우

사용자가 대본 생성을 요청하면, **반드시 먼저 아래 옵션을 확인**한다:

### 필수 확인 항목

1. **채널명**: 어떤 채널용인지 (channels/ 하위 폴더)
2. **주제**: 영상 주제
3. **언어**: 한국어(ko), English(en), 日本語(ja), 中文(zh), Español(es) — 기본: ko
4. **영상 길이**: 1~30분 범위 — 기본: 10분
5. **TTS 목소리**: Kore(여,차분), Aoede(여,경쾌), Charon(남,안정), Fenrir(남,활기), Puck(남,친근), Zephyr(중성) — 기본: 언어별 자동 선택

사용자가 일부만 지정한 경우, 지정하지 않은 항목은 기본값을 사용한다.
모든 항목을 한꺼번에 물어보지 말고, 주제와 채널만 있으면 나머지는 기본값으로 바로 진행해도 된다.

### 예시 대화

```
사용자: "채널: why-only-jesus, 주제: 뇌가소성, 영상 만들어줘"
→ 롱폼(10분, 16:9) + 숏츠(60초, 9:16) 자동 생성

사용자: "채널: my_channel, 주제: AI의 미래, 대본만 만들어줘"
→ Phase 1만 실행
```

## 파이프라인 실행 순서

"영상 만들어줘" 명령 시 **롱폼 Phase 1→5** 순차 실행 후, **숏츠 Phase S1→S5** 자동 실행.

---

### 📺 롱폼 파이프라인 (16:9)

#### Phase 1. 대본 생성
`channels/{채널}/projects/{주제}/script.md`에 저장.
영상 길이에 맞게 대본 분량 조절 (1분 ≈ 250자 한국어 / 150 words 영어).

#### Phase 2. TTS 음성 생성
```bash
PYTHONIOENCODING=utf-8 py scripts/tts.py channels/{채널}/projects/{주제}/script.md channels/{채널}/projects/{주제}/audio.wav --lang ko --voice Kore
```
- settings.json에서 API 키 자동 로드
- 출력은 항상 `.wav` (TTS가 WAV로 출력하므로)

#### Phase 3. Whisper 자막 생성
```bash
PYTHONIOENCODING=utf-8 py scripts/whisper_srt.py channels/{채널}/projects/{주제}/audio.wav channels/{채널}/projects/{주제}/subtitle.srt --max-chars 15 --model base --lang ko
```

#### Phase 4. Whisk 이미지 + ffmpeg 모션 영상 생성
```bash
# 무료 모드 (기본)
PYTHONIOENCODING=utf-8 py scripts/whisk_visual.py channels/{채널}/projects/{주제}/script.md channels/{채널}/projects/{주제}/subtitle.srt channels/{채널}/projects/{주제}/visuals --lang ko --aspect-ratio 16:9

# 프리미엄 모드 (Grok 유료 API 사용)
PYTHONIOENCODING=utf-8 py scripts/whisk_visual.py channels/{채널}/projects/{주제}/script.md channels/{채널}/projects/{주제}/subtitle.srt channels/{채널}/projects/{주제}/visuals --lang ko --aspect-ratio 16:9 --quality premium
```
- `--quality free` (기본): Whisk → Stable Horde 폴백, ffmpeg 모션만 사용 (무료)
- `--quality premium`: Grok Aurora 이미지($0.07/장) + Hook 씬 Grok Video (유료)
- 대본을 **문장 단위**로 씬 분리 (30~40개 씬)
- Gemini Flash로 **실사풍 시네마틱** 이미지 프롬프트 자동 생성
- 이미지는 `.jpg`로 저장

#### Phase 4 병렬 실행 규칙 (sub-agent)

Phase 4 완료 후, 아래 작업을 **Sonnet 모델 background agent로 병렬 실행**한다:

```
Agent 1 (background, sonnet): YouTube 메타데이터 생성
  - 제목 (60자 이내, SEO 최적화)
  - 설명문 (해시태그 포함)
  - 태그 목록 (10~15개)
  → channels/{채널}/projects/{주제}/metadata.json 저장

Agent 2 (background, sonnet): 썸네일 생성
  - 대본 핵심 키워드로 썸네일 프롬프트 생성
  → channels/{채널}/projects/{주제}/thumbnail_prompt.txt 저장
  - Whisk API로 썸네일 이미지 1장 생성
  → channels/{채널}/projects/{주제}/thumbnail.jpg 저장

Agent 3 (background, sonnet): 숏츠 대본 생성 (Phase S1)
  - 롱폼 대본에서 가장 임팩트 있는 부분을 추출/재구성
  - 60초 분량 (약 250자 한국어)
  - 강한 훅으로 시작, "전체 영상은 채널에서" CTA로 마무리
  → channels/{채널}/projects/{주제}-shorts/script.md 저장
```

이 병렬 agent들은 Phase 5와 동시에 실행되므로 전체 파이프라인 시간을 단축한다.

#### Phase 5. CapCut 프로젝트 생성
```bash
PYTHONIOENCODING=utf-8 py scripts/capcut_project.py channels/{채널}/projects/{주제}/audio.wav channels/{채널}/projects/{주제}/subtitle.srt "프로젝트명" --aspect-ratio 16:9 --scenes-dir channels/{채널}/projects/{주제}/visuals
```

---

### 📱 숏츠 파이프라인 (9:16)

롱폼 Phase 5 완료 후 (또는 Agent 3의 숏츠 대본 완료 후) 자동 실행.

#### Phase S1. 숏츠 대본 생성
- 롱폼 대본에서 핵심 60초를 추출/재구성
- 강한 훅 → 핵심 메시지 → CTA
- `channels/{채널}/projects/{주제}-shorts/script.md`에 저장

#### Phase S2. 숏츠 TTS
```bash
PYTHONIOENCODING=utf-8 py scripts/tts.py channels/{채널}/projects/{주제}-shorts/script.md channels/{채널}/projects/{주제}-shorts/audio.wav --lang ko --voice Kore
```

#### Phase S3. 숏츠 Whisper 자막
```bash
PYTHONIOENCODING=utf-8 py scripts/whisper_srt.py channels/{채널}/projects/{주제}-shorts/audio.wav channels/{채널}/projects/{주제}-shorts/subtitle.srt --max-chars 10 --model base --lang ko
```
- 숏츠는 자막 최대 10자 (화면이 좁으므로)

#### Phase S4. 숏츠 이미지 + 모션
```bash
# --quality free 또는 --quality premium (롱폼과 동일 옵션)
PYTHONIOENCODING=utf-8 py scripts/whisk_visual.py channels/{채널}/projects/{주제}-shorts/script.md channels/{채널}/projects/{주제}-shorts/subtitle.srt channels/{채널}/projects/{주제}-shorts/visuals --lang ko --aspect-ratio 9:16
```
- 9:16 세로 비율로 이미지 생성
- 숏츠는 약 8~12개 씬

#### Phase S5. 숏츠 CapCut 프로젝트
```bash
PYTHONIOENCODING=utf-8 py scripts/capcut_project.py channels/{채널}/projects/{주제}-shorts/audio.wav channels/{채널}/projects/{주제}-shorts/subtitle.srt "프로젝트명-shorts" --aspect-ratio 9:16 --scenes-dir channels/{채널}/projects/{주제}-shorts/visuals
```

---

## 전체 파이프라인 실행 예시

사용자가 "영상 만들어줘"라고 하면:

```
📺 롱폼 (16:9)
1. [Phase 1] 대본 생성 → script.md
2. [Phase 2] TTS → audio.wav
3. [Phase 3] Whisper 자막 → subtitle.srt
4. [Phase 4] Whisk 이미지 + ffmpeg 모션 → visuals/
   ├─ [Background Agent] 메타데이터 → metadata.json
   ├─ [Background Agent] 썸네일 이미지 1장 → thumbnail.jpg
   └─ [Background Agent] 숏츠 대본 생성 → {주제}-shorts/script.md
5. [Phase 5] CapCut 프로젝트 생성

📱 숏츠 (9:16)
6. [Phase S2] 숏츠 TTS → audio.wav
7. [Phase S3] 숏츠 Whisper 자막 → subtitle.srt
8. [Phase S4] 숏츠 이미지 + ffmpeg 모션 → visuals/
9. [Phase S5] 숏츠 CapCut 프로젝트 생성

📁 바탕화면 출력
10. [Phase 6] 바탕화면 정리 출력
    → Desktop/유튜브 자동화/{제목}/롱폼/
    → Desktop/유튜브 자동화/{제목}/숏츠/
    → Desktop/유튜브 자동화/{제목}/썸네일/
11. 완료 보고
```

---

### 📁 Phase 6. 바탕화면 출력 정리

모든 파이프라인 완료 후, 결과물을 바탕화면에 정리하여 복사한다.

```
C:\Users\shinh\OneDrive\Desktop\유튜브 자동화\{제목}\
  롱폼/
    script.md          # 대본
    audio.wav          # 음성
    subtitle.srt       # 자막
    metadata.json      # YouTube 메타데이터
  숏츠/
    script.md
    audio.wav
    subtitle.srt
    metadata.json
  썸네일/
    thumbnail.jpg          # 롱폼 썸네일
    thumbnail_shorts.jpg   # 숏츠 썸네일
```

- `{제목}`은 대본의 메인 제목 (한글 가능)
- CapCut 프로젝트는 CapCut 앱에서 직접 열기 (별도 경로)
- visuals(이미지/모션 영상)는 CapCut 프로젝트에 포함되어 있으므로 별도 복사하지 않음

---

## 설정 파일

`settings.json`에 전역 설정이 저장되어 있다:
- `script.max_minutes`: 최대 영상 길이 (30분)
- `aspect_ratio.default`: 기본 화면 비율
- `language.default`: 기본 언어
- `tts.api_key`: Gemini API 키
- `subtitle.max_chars`: 자막 최대 글자 수
- `whisk.cookie`: Google Labs 세션 쿠키 (만료 시 갱신 필요)
- `xai.api_key`: Grok API 키 (향후 사용)

## 디렉토리 구조

```
youtube-auto/
  settings.json              # 전역 설정
  CLAUDE.md                  # 이 파일 (파이프라인 가이드)
  scripts/
    tts.py                   # Gemini TTS 음성 생성
    whisper_srt.py           # Whisper 기반 자막 생성
    whisk_visual.py          # Whisk 이미지 + ffmpeg 모션 영상 생성
    capcut_project.py        # CapCut 프로젝트 생성
    srt_generator.py         # (레거시) 비례 타이밍 자막 생성
  channels/
    {채널명}/
      projects/
        {주제}/                  # 롱폼 프로젝트
          script.md              # 대본
          audio.wav              # TTS 음성
          subtitle.srt           # Whisper 자막
          metadata.json          # YouTube 메타데이터
          thumbnail_prompt.txt   # 썸네일 프롬프트
          thumbnail.jpg          # 썸네일 이미지
          visuals/
            scenes.json          # 씬 정보 + 프롬프트
            scene_001.jpg        # 씬 이미지
            scene_001.mp4        # ffmpeg 모션 영상
            ...
        {주제}-shorts/           # 숏츠 프로젝트
          script.md
          audio.wav
          subtitle.srt
          visuals/
            scenes.json
            scene_001.jpg
            scene_001.mp4
            ...
```

## 주의사항

- `PYTHONIOENCODING=utf-8`을 명령어 앞에 붙여야 한국어 출력 오류가 안 남
- Python은 `py` 명령어로 실행 (python/python3 아님)
- Whisper 사용 시 `pip install openai-whisper` 필요
- CapCut 프로젝트 폴더명이 한글이면 인식 안 될 수 있음 → 영문/숫자 권장
- TTS 출력은 WAV 형식 → `.wav`로 저장
- Whisk 이미지는 JPEG → `.jpg`로 저장 (`.png` 아님)
- Whisk 쿠키 만료 시 Google Labs 로그인 후 쿠키 갱신 필요
- CapCut JSON으로 Ken Burns 키프레임은 작동하지 않음 → ffmpeg 모션 사용
- 모션 영상은 ffmpeg zoompan 필터로 로컬 생성 (무료, API 불필요)
- 이미지 프롬프트 스타일: photorealistic, cinematic film still, 8K (사용자 선호)
