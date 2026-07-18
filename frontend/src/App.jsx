import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Cell, Tooltip } from 'recharts';
import { Shield, Search, TrendingUp, AlertTriangle, MapPin, Users, Calendar, Activity } from 'lucide-react';

// API Base URL (auto-detects local development vs production deployment)
const API_URL = import.meta.env.VITE_API_URL || (
  typeof window !== 'undefined' && 
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:8000'
    : 'https://crime-prediction-dashboard-1u2j.onrender.com'
);

// Helper component to center and animate map viewpoint changes
function MapFocus({ center, zoom }) {
  const map = useMap();
  useEffect(() => {
    if (center) {
      map.setView(center, zoom || 8, { animate: true, duration: 1.2 });
    }
  }, [center, zoom, map]);
  return null;
}

export default function App() {
  // Dropdowns structure
  const [districtsMapping, setDistrictsMapping] = useState({});
  const [statesList, setStatesList] = useState([]);
  const [districtsList, setDistrictsList] = useState([]);

  // Selections
  const [selectedState, setSelectedState] = useState('');
  const [selectedDistrict, setSelectedDistrict] = useState('');
  const [selectedYear, setSelectedYear] = useState(2012);

  // Data fetching
  const [mapData, setMapData] = useState([]);
  const [mapLoading, setMapLoading] = useState(false);
  const [predictionResult, setPredictionResult] = useState(null);
  const [historyResult, setHistoryResult] = useState([]);
  const [loading, setLoading] = useState(false);

  // Selected item on map click
  const [clickedDistrict, setClickedDistrict] = useState(null);
  const [mapCenter, setMapCenter] = useState([21.0, 78.0]);
  const [mapZoom, setMapZoom] = useState(5);

  // Years array
  const years = Array.from({ length: 20 }, (_, i) => 2001 + i); // 2001 to 2020

  // 1. Fetch States and Districts Mapping on mount
  useEffect(() => {
    fetch(`${API_URL}/districts`)
      .then((res) => {
        if (!res.ok) throw new Error('API server is not responding.');
        return res.json();
      })
      .then((data) => {
        setDistrictsMapping(data);
        const states = Object.keys(data).sort();
        setStatesList(states);
      })
      .catch((err) => {
        console.error('Error fetching districts:', err);
      });
  }, []);

  // 2. Fetch Map Data whenever Year changes
  useEffect(() => {
    setMapLoading(true);
    fetch(`${API_URL}/map-data?year=${selectedYear}`)
      .then((res) => res.json())
      .then((data) => {
        setMapData(data);
        setMapLoading(false);
      })
      .catch((err) => {
        console.error('Error fetching map data:', err);
        setMapLoading(false);
      });
  }, [selectedYear]);

  // Handle State dropdown change
  const handleStateChange = (e) => {
    const state = e.target.value;
    setSelectedState(state);
    setSelectedDistrict('');
    if (state && districtsMapping[state]) {
      setDistrictsList(districtsMapping[state].sort());
    } else {
      setDistrictsList([]);
    }
  };

  // Run predictions or lookups
  const handlePredict = (e) => {
    e.preventDefault();
    if (!selectedState || !selectedDistrict) return;

    setLoading(true);
    setClickedDistrict(null); // clear clicked district sidebar to focus on prediction

    // Fetch /predict and /history in parallel
    Promise.all([
      fetch(`${API_URL}/predict?state=${encodeURIComponent(selectedState)}&district=${encodeURIComponent(selectedDistrict)}&year=${selectedYear}`).then(res => res.json()),
      fetch(`${API_URL}/history?state=${encodeURIComponent(selectedState)}&district=${encodeURIComponent(selectedDistrict)}`).then(res => res.json())
    ])
      .then(([pred, hist]) => {
        setPredictionResult(pred);
        setHistoryResult(hist);
        setLoading(false);

        // Try to center map on the searched district's coordinates
        const distMatch = mapData.find(
          (d) => d.state === selectedState && d.district === selectedDistrict
        );
        if (distMatch) {
          setMapCenter([distMatch.latitude, distMatch.longitude]);
          setMapZoom(8);
        }
      })
      .catch((err) => {
        console.error('Error fetching predictions:', err);
        setLoading(false);
      });
  };

  // Handle circle click on Leaflet map
  const handleCircleClick = (districtItem) => {
    setClickedDistrict(districtItem);
    setPredictionResult(null); // clear active predict sidebar to focus on clicked item
    
    // Sync dropdowns with clicked item
    setSelectedState(districtItem.state);
    if (districtsMapping[districtItem.state]) {
      setDistrictsList(districtsMapping[districtItem.state].sort());
    }
    setSelectedDistrict(districtItem.district);

    // Fetch history for clicked district
    fetch(`${API_URL}/history?state=${encodeURIComponent(districtItem.state)}&district=${encodeURIComponent(districtItem.district)}`)
      .then((res) => res.json())
      .then((hist) => {
        setHistoryResult(hist);
      })
      .catch((err) => {
        console.error('Error fetching history:', err);
      });
  };

  // Color mapper based on risk level
  const getColorForRisk = (risk) => {
    switch (risk?.toUpperCase()) {
      case 'HIGH':
        return '#ef4444'; // Red
      case 'MEDIUM':
        return '#f97316'; // Orange
      case 'LOW':
        return '#22c55e'; // Green
      default:
        return '#94a3b8'; // Slate
    }
  };

  // Format number with commas
  const formatNumber = (num) => {
    return num?.toLocaleString('en-IN') || '0';
  };

  // Prepare chart data for display
  const getChartData = (predictionObj) => {
    if (!predictionObj) return [];
    return Object.entries(predictionObj).map(([name, val]) => ({
      name,
      percentage: val * 100,
      value: val
    }));
  };

  // Determine current active district details to display in sidebar
  const activeDetails = clickedDistrict || predictionResult;
  const isPredictionMode = !!predictionResult;

  const chartData = activeDetails
    ? getChartData(activeDetails.crime_prediction || activeDetails.crime_prediction)
    : [];

  return (
    <div className="app-container">
      {/* 1. Sidebar Panel */}
      <aside className="sidebar">
        <div className="logo-container">
          <div className="logo-icon">
            <Shield size={20} strokeWidth={2.5} />
          </div>
          <span className="logo-text">CrimeShield India</span>
        </div>

        {/* Search Panel */}
        <div className="glass-card">
          <form onSubmit={handlePredict}>
            <div className="form-group">
              <label className="form-label">State</label>
              <select
                className="form-select"
                value={selectedState}
                onChange={handleStateChange}
                required
              >
                <option value="">Select State</option>
                {statesList.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">District</label>
              <select
                className="form-select"
                value={selectedDistrict}
                onChange={(e) => setSelectedDistrict(e.target.value)}
                disabled={!selectedState}
                required
              >
                <option value="">Select District</option>
                {districtsList.map((dist) => (
                  <option key={dist} value={dist}>
                    {dist}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Year</label>
              <select
                className="form-select"
                value={selectedYear}
                onChange={(e) => setSelectedYear(parseInt(e.target.value))}
              >
                {years.map((yr) => (
                  <option key={yr} value={yr}>
                    {yr}
                  </option>
                ))}
              </select>
            </div>

            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? (
                <>
                  <div className="spinner"></div> Processing...
                </>
              ) : (
                <>
                  <Activity size={16} /> Predict Hotspot & Crime
                </>
              )}
            </button>
          </form>
        </div>

        {/* 2. Details and Chart Panel */}
        {activeDetails ? (
          <div className="glass-card" style={{ flexGrow: 1, margin: 0 }}>
            <div className="result-header">
              <div>
                <h3 className="result-title" style={{ fontFamily: 'var(--font-heading)', fontWeight: 700 }}>
                  {activeDetails.district}
                </h3>
                <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  {activeDetails.state}
                </span>
              </div>
              <span className={`badge ${isPredictionMode || activeDetails.is_prediction ? 'badge-prediction' : 'badge-actual'}`}>
                {isPredictionMode || activeDetails.is_prediction ? 'ML Prediction' : `Actual (${selectedYear})`}
              </span>
            </div>

            <div className={`risk-badge ${activeDetails.risk_level?.toLowerCase()}`}>
              Risk Level: {activeDetails.risk_level}
            </div>

            <div className="metric-grid">
              <div className="metric-card">
                <div className="metric-label">Predicted Cases</div>
                <div className="metric-value">
                  {formatNumber(activeDetails.total_predicted ?? activeDetails.total_crimes)}
                </div>
              </div>
              <div className="metric-card">
                <div className="metric-label">Crime Rate /100k</div>
                <div className="metric-value">
                  {activeDetails.crime_rate_per_100k ?? roundRate(activeDetails.total_crimes, activeDetails.population)}
                </div>
              </div>
            </div>

            {chartData.length > 0 ? (
              <div style={{ marginBottom: '24px' }}>
                <span className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <TrendingUp size={14} /> Crime Type Likelihood
                </span>
                <div className="chart-container">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={chartData}
                      layout="vertical"
                      margin={{ top: 5, right: 10, left: -25, bottom: 5 }}
                    >
                      <XAxis type="number" domain={[0, 100]} hide />
                      <YAxis
                        type="category"
                        dataKey="name"
                        stroke="#94a3b8"
                        fontSize={11}
                        tickLine={false}
                        axisLine={false}
                        width={80}
                      />
                      <Tooltip
                        formatter={(value) => [`${value.toFixed(1)}%`, 'Probability']}
                        contentStyle={{
                          background: 'rgba(10, 12, 26, 0.95)',
                          borderColor: 'var(--border-glass)',
                          borderRadius: '8px',
                          color: '#fff',
                          fontFamily: 'var(--font-body)',
                          fontSize: '12px'
                        }}
                      />
                      <Bar dataKey="percentage" radius={[0, 4, 4, 0]} barSize={10}>
                        {chartData.map((entry, index) => (
                          <Cell
                            key={`cell-${index}`}
                            fill={
                              index === 0
                                ? 'var(--primary)'
                                : index === 1
                                ? 'var(--accent)'
                                : 'rgba(255,255,255,0.15)'
                            }
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ) : null}

            {/* Historical Trend Records */}
            {historyResult.length > 0 ? (
              <div>
                <span className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Calendar size={14} /> Historical Crime Trend
                </span>
                <div className="list-history">
                  {historyResult.map((record) => (
                    <div className="history-item" key={record.year}>
                      <span className="history-year">{record.year}</span>
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        Rate: {((record.total_ipc_crimes / activeDetails.population) * 100000).toFixed(1)}
                      </span>
                      <span className="history-count">
                        {formatNumber(record.total_ipc_crimes)} cases
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : (
          /* Welcome Card */
          <div className="glass-card" style={{ flexGrow: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center', padding: '32px', margin: 0 }}>
            <div
              style={{
                width: '64px',
                height: '64px',
                borderRadius: '50%',
                background: 'rgba(99, 102, 241, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--primary)',
                marginBottom: '20px',
                border: '1px solid rgba(99, 102, 241, 0.2)'
              }}
            >
              <AlertTriangle size={28} />
            </div>
            <h4 style={{ fontFamily: 'var(--font-heading)', fontWeight: 600, fontSize: '16px', marginBottom: '8px' }}>
              No District Selected
            </h4>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              Click on a colored district circle on the map of India or search for a specific district in the panel above to view predictive risk charts.
            </p>
          </div>
        )}
      </aside>

      {/* 3. Main Map Section */}
      <main className="map-container">
        {mapLoading && (
          <div
            style={{
              position: 'absolute',
              top: '24px',
              left: '50%',
              transform: 'translateX(-50%)',
              background: 'rgba(10, 12, 26, 0.95)',
              border: '1px solid var(--border-glass)',
              padding: '10px 20px',
              borderRadius: '20px',
              zIndex: 1000,
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              backdropFilter: 'var(--glass-blur)',
              boxShadow: 'var(--shadow-main)'
            }}
          >
            <div className="spinner"></div> Syncing map hotspots for year {selectedYear}...
          </div>
        )}

        <MapContainer
          center={mapCenter}
          zoom={mapZoom}
          id="leaflet-map"
          zoomControl={false}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />

          <MapFocus center={mapCenter} zoom={mapZoom} />

          {/* Render glowing colored markers for all districts */}
          {mapData.map((d, index) => (
            <CircleMarker
              key={`${d.state}-${d.district}-${index}`}
              center={[d.latitude, d.longitude]}
              radius={7 + (d.total_crimes ? Math.min(10, Math.sqrt(d.total_crimes) * 0.15) : 0)}
              fillColor={getColorForRisk(d.risk_level)}
              color="#ffffff"
              weight={0.8}
              fillOpacity={0.65}
              eventHandlers={{
                click: () => handleCircleClick(d),
              }}
            >
              <Popup>
                <div style={{ padding: '2px' }}>
                  <h4 style={{ margin: '0 0 4px 0', fontSize: '13px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <MapPin size={12} color="var(--primary)" /> {d.district}
                  </h4>
                  <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                    {d.state}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', borderTop: '1px solid var(--border-glass)', paddingTop: '6px', fontSize: '11px' }}>
                    <div>Risk Level: <strong style={{ color: getColorForRisk(d.risk_level) }}>{d.risk_level}</strong></div>
                    <div>Cases: <strong>{formatNumber(d.total_crimes)}</strong></div>
                    <div>Rate/100k: <strong>{d.crime_rate_per_100k}</strong></div>
                  </div>
                </div>
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>

        {/* Map Legend Overlay */}
        <div className="map-legend">
          <div className="legend-title">Risk Classification</div>
          <div className="legend-item">
            <div className="legend-color high"></div>
            <span>High Risk (&gt; 384/100k)</span>
          </div>
          <div className="legend-item">
            <div className="legend-color medium"></div>
            <span>Medium Risk (145 - 384)</span>
          </div>
          <div className="legend-item">
            <div className="legend-color low"></div>
            <span>Low Risk (&lt; 145/100k)</span>
          </div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', borderTop: '1px solid var(--border-glass)', paddingTop: '6px', marginTop: '4px' }}>
            Map Year: {selectedYear}
          </div>
        </div>
      </main>
    </div>
  );
}

// Simple Helper to calculate rate on the fly if needed
function roundRate(crimes, pop) {
  if (!pop) return '0.0';
  return ((crimes / pop) * 100000).toFixed(2);
}
