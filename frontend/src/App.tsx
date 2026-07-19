import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import ChatPage from './pages/ChatPage';
import SettingsPage from './pages/SettingsPage';
import DocumentsPage from './pages/DocumentsPage';
import GalleryPage from './pages/GalleryPage';
import EmailPage from './pages/EmailPage';
import CalendarPage from './pages/CalendarPage';
import TasksPage from './pages/TasksPage';
import './App.css';

const PlaceholderPage = ({ title }: { title: string }) => (
  <div className="page-placeholder">
    <h1>{title}</h1>
    <p>This module is currently being migrated to React.</p>
  </div>
);

function App() {
  return (
    <Router>
      <div className="app-container">
        <Sidebar />
        <main className="main-content">
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/gallery" element={<GalleryPage />} />
            <Route path="/email" element={<EmailPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/cookbook" element={<PlaceholderPage title="Cookbook" />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
