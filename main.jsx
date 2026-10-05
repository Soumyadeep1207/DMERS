import React from 'react';
import { createRoot } from 'react-dom/client';
import 'leaflet/dist/leaflet.css';
import './styles.css';
import './map.css';
import App from './RealMapApp.jsx';
createRoot(document.getElementById('root')).render(<App />);
