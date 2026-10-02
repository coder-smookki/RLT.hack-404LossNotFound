import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './app/App.js';
import './styles/global.css';
const root = document.getElementById('root');
if (!root) throw Error('Root element missing');
createRoot(root).render(<App />);
