import React from 'react';
import { createRoot } from 'react-dom/client';

import './index.css';
import ChatPanel from './components/ChatPanel';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ChatPanel />
  </React.StrictMode>,
);
