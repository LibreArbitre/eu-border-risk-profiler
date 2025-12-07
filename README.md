# EU Border Risk Profiler

The **EU Border Risk Profiler** is a specialized intelligence system designed to monitor and forecast asylum application pressure at EU external borders. It leverages historical Eurostat data to calculate real-time "Risk Scores" and predict future trends using machine learning.

![EU Border Risk Profiler Dashboard](https://github.com/user-attachments/assets/placeholder-image-url)
*(Screenshot of the dashboard showing the heatmap and ranking)*

## 🚀 Key Features

*   **Advanced Risk Scoring**: Uses a logarithmic global normalization formula to identify high-risk zones without being skewed by historical outliers (e.g., the 2015 crisis).
    *   `Risk = (log(Volume) / log(Global_Max)) * (1 + Trend_Variation)`
*   **Smart Data Ingestion**: Automatically handles data lags (e.g., when some countries report a month later than others) to ensure the heatmap always reflects the *latest valid* intelligence.
*   **Predictive Modeling**: Trains Random Forest regressors for each of the 27 EU countries to forecast pressure 3 months ahead.
*   **Advanced Dashboard**: A "Situation Room" style interface built with Streamlit, featuring dynamic heatmaps, risk rankings, and country-level deep dives.

## 🛠️ Architecture

*   **PostgreSQL (`db`)**: Stores raw `asylum_data` and computed `risk_predictions`.
*   **Data Harvester (`data_harvester`)**: Robust pipeline fetching `migr_asyappctzm` from Eurostat Bulk API. Handles partial updates and data cleaning.
*   **Risk Predictor (`risk_predictor`)**: The core intelligence engine. Runs daily to retrain models and generate fresh risk scores.
*   **API Service (`api_service`)**: FastAPI backend serving data to the frontend.
*   **Dashboard (`dashboard`)**: Streamlit-based UI for analysts.

## 🚦 Quick Start

1.  **Prerequisites**: Docker & Docker Compose.
2.  **Launch**:
    ```bash
    docker-compose up --build -d
    ```
3.  **Access**:
    *   **Dashboard**: `http://localhost:8501`
    *   **API Docs**: `http://localhost:8000/docs`

## 🧠 Technical Details

### The Risk Formula
The system calculates a "Risk Score" (0-100) for every country/month.
- **Volume Component**: Normalized logarithmically against the all-time EU high (1.3M applications in 2015). This ensures that a current crisis (e.g., 100k) registers as "High Risk" (~85/100) rather than "Low" compared to the past.
- **Trend Component**: Adjusts the score based on month-over-month variation (acceleration/deceleration).

### Data Handling
Eurostat data often has gaps. Germany might report October numbers while Spain is still on September.
- The **Harvester** collects everything.
- The **Predictor** intelligently ignores the last month if it contains `0` (missing) but determining that the previous month was active, ensuring distinct "Latest Available" dates per country.
- The **Dashboard** aggregates these mixed dates to show a complete European map.

## 📂 Project Structure

```
eu-border-risk-profiler/
├── api_service/      # FastAPI backend
├── dashboard/        # Streamlit frontend (logic + UI)
├── data_harvester/   # Eurostat parser & loader
├── risk_predictor/   # ML training & scoring engine
└── docker-compose.yml
```

## 🛡️ License

Private / Internal Use. 
Designed for geopolitical analysis and border pressure forecasting.
