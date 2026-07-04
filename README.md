# MeteoCity - City-Level Weather Monitoring & Heat Trend Analysis Platform

MeteoCity is a city-level weather monitoring application developed for the Software Engineering for Geoinformatics course (A.Y. 2025/26) at Politecnico di Milano. It tracks and visualizes historical and near-real-time weather data for **Milan** and **Rome**, using the Meteostat API (via RapidAPI) as its data source.

**Team — Group 9**
- Ayman Mutasim
- Mobina Faraji
- Hangyun Wang

---

## Overview

MeteoCity follows a three-tier architecture:

```
Flask REST API  →  PostgreSQL Database  →  Streamlit Dashboard
   (backend)          (data storage)          (visualization)
```

The system ingests weather observations from four real monitoring stations across Milan and Rome, stores them in a relational database, and presents them through an interactive dashboard with maps, trend charts, and per-station statistics.

### Monitored stations

| Station | City | Meteostat ID |
|---|---|---|
| Milano Malpensa | Milan | 16080 |
| Milano Linate | Milan | 16066 |
| Roma Fiumicino | Rome | 16242 |
| Roma Ciampino | Rome | 16239 |

---

## Features

- **Interactive map** with color-coded station markers (Folium), reflecting the most recent observation per station
- **Trend analysis charts** (Plotly) for Temperature, Humidity, and Wind Speed over a user-selected date range
- **Per-station statistics** with deduplicated station details
- **Variable-specific legends and thresholds** for each weather metric
- **User registration and login system**, including an NGO account type
- **Automatic data mode**: runs on mock/synthetic data out of the box, or live Meteostat data once a RapidAPI key is provided

---

## Tech Stack

- **Backend:** Flask (REST API), SQLAlchemy ORM
- **Database:** PostgreSQL
- **Frontend/Dashboard:** Streamlit, Folium (maps), Plotly (charts)
- **Data source:** Meteostat API via RapidAPI
- **Environment:** Anaconda Python

---

## Project Structure

```
Software-Engineering-Project-Group_9/
├── backend/
│   ├── __init__.py
│   ├── app.py                 # Flask app entry point
│   ├── config.py              # App configuration
│   ├── clean_db.py            # Database cleanup utility
│   ├── .env.example           # Template for environment variables
│   ├── routes/                # API route definitions
│   └── ingestion/             # Meteostat data ingestion logic
├── dashboard/
│   └── meteocity_dashboard.py # Streamlit dashboard
├── tests/                     # Automated tests
├── FINAL_VERSION_RASD.pdf     # Requirements Analysis and Specification Document
├── FINAL_VERSION_DD.pdf       # Design Document
├── FINAL_VERSION_SRD.pdf      # Software Requirements Document
├── requirements.txt
└── README.md
```

---

## Getting Started

### Prerequisites

- **PostgreSQL** installed locally, with a database named `meteocity` created manually (no PostGIS required)
- **Anaconda Python**
- A **RapidAPI account** with a Meteostat API key *(optional — the app runs on mock data without it)*

### 1. Clone the repository

```bash
git clone https://github.com/Ayman1017/Software-Engineering-Project-Group_9.git
cd Software-Engineering-Project-Group_9
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```
*(only needed once per environment)*

### 3. Configure environment variables

Copy the example file and fill in your own values:

```bash
cd backend
copy .env.example .env      # Windows
# or: cp .env.example .env  # macOS/Linux
```

Edit `backend/.env` and set:
```
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/meteocity
RAPIDAPI_KEY=your_rapidapi_key_here
```

> Leaving `RAPIDAPI_KEY` empty automatically switches the app into mock/synthetic data mode. `backend/.env` is git-ignored and must be created locally — it is never committed.

### 4. Run the application

The backend auto-creates the database schema on first run. Two terminals are required:

**Terminal 1 — Backend (Flask API, port 5000)**
```bash
cd backend
python app.py
```

**Terminal 2 — Dashboard (Streamlit, from project root)**
```bash
streamlit run dashboard/meteocity_dashboard.py
```

The dashboard will be available at `http://localhost:8501`.

---

## Data Modes

MeteoCity supports two data modes, indicated per record via an inferred `is_synthetic` flag:

- **Live data:** Real observations pulled from Meteostat via RapidAPI (available when `RAPIDAPI_KEY` is set)
- **Mock/synthetic data:** Generated automatically when no API key is provided, or to fill gaps

**Note on date ranges:** Meteostat enforces a hard 30-day maximum per API request. For user-selected ranges longer than 30 days, MeteoCity automatically supplements missing data with synthetic values (using `ON CONFLICT DO NOTHING`, so real data is never overwritten). Real Meteostat data is only guaranteed for ranges of 30 days or fewer; longer ranges will be a blend of real and synthetic data.

---

## API Usage Note

The Meteostat free plan allows **500 requests/month** — be mindful of this when testing with a live API key.

---

## Documentation

Full project documentation is available in this repository:
- `FINAL_VERSION_RASD.pdf` — Requirements Analysis and Specification Document
- `FINAL_VERSION_DD.pdf` — Design Document
- `FINAL_VERSION_SRD.pdf` — Software Requirements Document

---

## Known Limitations

- Login and data fetching for the first time may take up to 1 minute .
- Real weather data is only available for four hardcoded stations (Milano Malpensa, Milano Linate, Roma Fiumicino, Roma Ciampino); other cities are not supported.
- If no valid RapidAPI key is configured, the system falls back entirely to mock/synthetic data.

---

## Future Work

- Full cloud deployment: Streamlit Community Cloud (dashboard) + Render (Flask backend) + managed cloud PostgreSQL
- Replace hardcoded `localhost:5000` backend URL with an environment variable ahead of deployment

---

## License

This project is licensed under the MIT License — see the `LICENSE` file for details.
