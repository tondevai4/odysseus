import React, { useState } from 'react';
import { User, Shield, HardDrive, Palette, Globe, Key } from 'lucide-react';
import './SettingsPage.css';

const SettingsPage = () => {
  const [activeTab, setActiveTab] = useState('account');

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2>Settings</h2>
      </div>

      <div className="settings-layout">
        <aside className="settings-sidebar">
          <button 
            className={`settings-tab ${activeTab === 'account' ? 'active' : ''}`}
            onClick={() => setActiveTab('account')}
          >
            <User size={18} /> Account
          </button>
          <button 
            className={`settings-tab ${activeTab === 'providers' ? 'active' : ''}`}
            onClick={() => setActiveTab('providers')}
          >
            <Globe size={18} /> Providers & Models
          </button>
          <button 
            className={`settings-tab ${activeTab === 'security' ? 'active' : ''}`}
            onClick={() => setActiveTab('security')}
          >
            <Shield size={18} /> Security & Auth
          </button>
          <button 
            className={`settings-tab ${activeTab === 'api' ? 'active' : ''}`}
            onClick={() => setActiveTab('api')}
          >
            <Key size={18} /> API Tokens
          </button>
          <button 
            className={`settings-tab ${activeTab === 'appearance' ? 'active' : ''}`}
            onClick={() => setActiveTab('appearance')}
          >
            <Palette size={18} /> Appearance
          </button>
          <button 
            className={`settings-tab ${activeTab === 'storage' ? 'active' : ''}`}
            onClick={() => setActiveTab('storage')}
          >
            <HardDrive size={18} /> Data & Storage
          </button>
        </aside>

        <main className="settings-content">
          {activeTab === 'account' && (
            <div className="settings-panel">
              <h3>Account Settings</h3>
              <p className="settings-desc">Manage your profile and privileges.</p>
              
              <div className="settings-group">
                <label>Username</label>
                <input type="text" className="settings-input" defaultValue="admin" disabled />
              </div>
              <div className="settings-group">
                <label>Display Name</label>
                <input type="text" className="settings-input" placeholder="How should the agent call you?" />
              </div>
            </div>
          )}

          {activeTab === 'appearance' && (
            <div className="settings-panel">
              <h3>Appearance</h3>
              <p className="settings-desc">Customize the look and feel of Odysseus.</p>
              
              <div className="theme-grid">
                <div className="theme-card active">
                  <div className="theme-preview" style={{ background: '#0b0f19' }}></div>
                  <span>Vanta (Default)</span>
                </div>
                <div className="theme-card">
                  <div className="theme-preview" style={{ background: '#f8fafc' }}></div>
                  <span>Light</span>
                </div>
                <div className="theme-card">
                  <div className="theme-preview" style={{ background: '#0a0a0a' }}></div>
                  <span>Midnight</span>
                </div>
              </div>
            </div>
          )}

          {/* Placeholder for other tabs */}
          {['providers', 'security', 'api', 'storage'].includes(activeTab) && (
            <div className="settings-panel">
              <h3>{activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}</h3>
              <p className="settings-desc">This section is currently being migrated to React.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default SettingsPage;
