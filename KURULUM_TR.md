# Hızlı kurulum ve çalıştırma (Türkçe)

Bu klasör projenin iki fazını da içerir:

* **Faz 1:** veri hazırlama ve istatistiksel analiz (`run_all.py`)
* **Faz 2:** istatistiklerin tamamlanması ve tahmin modelleri (`run_phase2.py`)
* **Ek:** gelecekteki bir maç için trafik tahmin paneli (`run_scenario.py`, `panel.py`)
* **Ek doğrulama:** Ocak 2025 sonrasına da uzanan iki açık İBB kaynağı, metro girişleri ve UYM duyuruları (`run_extra.py`)

Final teslimde iki rapor var. **Tam proje raporu** (`Project_Report.pdf`) Faz 1 raporunun şablonunda devam eder;
`python tools/build_final_report.py` onu teslim edilen Faz 1 raporundan üretir (çıktı `teslim/Final_Report.docx` / `.pdf`).
**Araştırma makalesi** (`Research_Paper_IEEE.pdf`, 10 sayfa) IEEE konferans formatında bir LaTeX makalesidir (`paper/`
klasörü). Yeniden derlemek için `Final_Paper_Overleaf.zip` dosyasını Overleaf'te **New Project → Upload Project** ile
yükleyip **Recompile** deyin (derleyici: pdfLaTeX). Bütün veri setlerinin bağlantıları `Dataset_Links.txt` dosyasında. Faz 1'de teslim edilen rapor
`docs/Phase1_Report_submitted.docx` olarak duruyor.

## 1. Tek komutla çalıştırma

Python 3.9 veya üstü gerekli (`python3 --version`).

**macOS / Linux:** klasörde bir Terminal açın:

```
bash run.sh --offline
```

**Windows:** `run.bat --offline`

Komut klasörün içinde `.venv` adında ayrı bir Python ortamı kurar, paketleri yükler, Faz 1 veri
setini `data/raw/` içindeki ham dosyalardan yeniden üretir, Faz 2'yi çalıştırır ve makalenin
sayılarını, tablolarını ve şekillerini yazar. `--offline` olmadan İBB trafik verisi ve hava durumu
yeniden indirilir. Tamamı yaklaşık 10 dakika sürer; zamanın çoğu model eğitimi.

## 2. Parça parça çalıştırma

```
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_all.py --offline            # Faz 1 (~1 dk)
python run_phase2.py --part stats      # Faz 2 istatistikler (saniyeler)
python run_phase2.py --part model      # Faz 2 modeller (~8 dk)
python tools/build_paper.py            # makale sayıları + Final_Paper_Overleaf.zip
python run_scenario.py                 # Ek: uzun vadeli maç modeli (~2 dk)
python panel.py                        # Ek: tahmin paneli, tarayıcıda http://127.0.0.1:8050
python run_extra.py                    # Ek doğrulama: metro girişleri ve UYM duyuruları (internetsiz çalışır)
```

## 3. Sonuçlar nerede

| Klasör / dosya | İçerik |
|---|---|
| `outputs/report_values.json` | Faz 1 raporundaki bütün sayılar |
| `outputs/phase2_values.json` | Faz 2'deki bütün sayılar (testler ve modeller) |
| `outputs/tables/phase2/` | Holm düzeltmeli testler, rakip analizi, duyarlılık analizi, model sonuçları |
| `outputs/figures/phase2/` | Model karşılaştırma, tahmin edilen ve gözlenen maç profili, karışıklık matrisi, özellik grubu önemi, rakip grupları |
| `outputs/phase2_model_log.txt` | Model eğitiminin çıktısı |
| `paper/generated/values.tex` | Makaledeki bütün sayılar (elle yazılmış sonuç yok) |
