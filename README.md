# 공정 물류 시뮬레이션 (Streamlit)

SimPy 기반 이산사건 시뮬레이션과 Streamlit 대시보드입니다.

## 로컬 실행

```bash
pip install -r requirements.txt
streamlit run webapp.py
```

Windows에서는 `run_web.bat`을 실행해도 됩니다.

## 공정 기본값 (Excel)

`data/` 폴더에 `.xlsx` 공정 설정 파일이 있으면(예: `공정설정값260520.xlsx`), 앱 기동 시 **「설비·공정 확인」** 시트의 **시뮬 현재값** 열을 읽어 `SimulationConfig` 기본값으로 씁니다.  
파일이 없거나 읽기에 실패하면 `config.py`의 내장 기본값으로 폴백합니다. 사이드바에서 모든 주요 수치를 다시 조정할 수 있습니다.

## 공정 맥락 문서 (Markdown)

운영·공정 서술은 `data/공정설명260521.md` 등 마크다운으로 관리합니다. 웹 앱에는 **공정 설명 전용 탭이 없으며**, IDE나 텍스트 편집기로 해당 파일을 직접 수정하면 됩니다.  
**🔤 용어·약어** 탭은 선택적으로 같은 파일 안의 **「웹·대시보드에서 쓰는 용어 약어」** 절을 읽어 표시합니다(절이 없으면 앱 내장 표를 씁니다).

## Vercel에 대해

**이 저장소는 Streamlit 앱이라 Vercel에 그대로 배포할 수 없습니다.**  
Vercel은 짧게 끝나는 서버리스 함수·정적 프런트엔드에 맞고, Streamlit은 **항상 켜져 있는 Python 웹 서버·WebSocket**이 필요합니다.

대신 아래 중 하나를 권장합니다.

### 1) Streamlit Community Cloud (GitHub만으로 가장 간단)

1. [share.streamlit.io](https://share.streamlit.io)에 GitHub로 로그인합니다.
2. **New app** → 저장소 `ejavm83/src_sim`, 브랜치 `main`, **Main file path**에 `webapp.py`를 지정합니다.
3. (선택) **Secrets**에 다음을 넣으면 UI에 키를 다시 입력하지 않아도 됩니다.

   ```toml
   GEMINI_API_KEY = "여기에_키"
   display_name = "표시 이름(선택)"
   ```

   또는 배포 플랫폼 환경 변수로 `GEMINI_API_KEY`를 설정해도 됩니다.

4. **Deploy**를 누르면 공개 URL이 발급됩니다.

의존성에 `ortools` 등이 있어 **첫 빌드가 수 분** 걸릴 수 있습니다.

### 2) Docker로 Railway / Render / Google Cloud Run 등

저장소 루트의 `Dockerfile`로 이미지를 빌드한 뒤, 해당 서비스에서 **컨테이너 포트 8501**을 외부에 노출하면 됩니다.

```bash
docker build -t scr-sim .
docker run -p 8501:8501 -e GEMINI_API_KEY=your_key scr-sim
```

## 설정 파일

- 로컬: `local_settings.json`(Git에 올리지 마세요. `.gitignore`에 포함됨)
- 클라우드: 위 Secrets 또는 환경 변수 `GEMINI_API_KEY`, `GEMINI_DISPLAY_NAME`
