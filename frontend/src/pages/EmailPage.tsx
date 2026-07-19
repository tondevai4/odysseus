import React, { useState } from 'react';
import { Inbox, Send, Archive, Trash2, PenBox, Search, Star, MoreVertical, Reply, Forward } from 'lucide-react';
import './EmailPage.css';

interface Email {
  id: string;
  sender: string;
  subject: string;
  preview: string;
  date: string;
  unread: boolean;
  starred: boolean;
}

const EmailPage = () => {
  const [emails] = useState<Email[]>([
    { id: '1', sender: 'GitHub', subject: 'Security alert: vulnerable dependency', preview: 'We found a potential security vulnerability...', date: '10:42 AM', unread: true, starred: false },
    { id: '2', sender: 'Odysseus Alerts', subject: 'Task completed successfully', preview: 'Your scheduled deep research task has finished...', date: 'Yesterday', unread: false, starred: true },
    { id: '3', sender: 'Alex Jones', subject: 'V3 Overhaul Ideas', preview: 'Hey, I was thinking about the new React rewrite...', date: 'Jul 7', unread: false, starred: false },
  ]);
  const [activeEmail, setActiveEmail] = useState<string>('1');
  const [activeFolder, setActiveFolder] = useState<string>('inbox');

  const selectedEmail = emails.find(e => e.id === activeEmail);

  return (
    <div className="email-page">
      <div className="email-sidebar">
        <div className="email-compose-area">
          <button className="primary-btn w-full justify-center"><PenBox size={18} /> Compose</button>
        </div>
        
        <nav className="email-folders">
          <button className={`folder-btn ${activeFolder === 'inbox' ? 'active' : ''}`} onClick={() => setActiveFolder('inbox')}>
            <Inbox size={18} /> Inbox <span className="badge">1</span>
          </button>
          <button className={`folder-btn ${activeFolder === 'sent' ? 'active' : ''}`} onClick={() => setActiveFolder('sent')}>
            <Send size={18} /> Sent
          </button>
          <button className={`folder-btn ${activeFolder === 'starred' ? 'active' : ''}`} onClick={() => setActiveFolder('starred')}>
            <Star size={18} /> Starred
          </button>
          <button className={`folder-btn ${activeFolder === 'archive' ? 'active' : ''}`} onClick={() => setActiveFolder('archive')}>
            <Archive size={18} /> Archive
          </button>
          <button className={`folder-btn ${activeFolder === 'trash' ? 'active' : ''}`} onClick={() => setActiveFolder('trash')}>
            <Trash2 size={18} /> Trash
          </button>
        </nav>
      </div>

      <div className="email-list-area">
        <div className="email-search">
          <Search size={16} className="search-icon" />
          <input type="text" placeholder="Search emails..." />
        </div>

        <div className="email-list">
          {emails.map(email => (
            <div 
              key={email.id} 
              className={`email-item ${activeEmail === email.id ? 'active' : ''} ${email.unread ? 'unread' : ''}`}
              onClick={() => setActiveEmail(email.id)}
            >
              <div className="email-item-header">
                <span className="email-sender">{email.sender}</span>
                <span className="email-date">{email.date}</span>
              </div>
              <div className="email-subject">{email.subject}</div>
              <div className="email-preview-text">{email.preview}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="email-viewer-area">
        {selectedEmail ? (
          <div className="email-viewer">
            <div className="email-viewer-header">
              <div className="email-viewer-actions">
                <button className="icon-btn" title="Archive"><Archive size={18} /></button>
                <button className="icon-btn" title="Delete"><Trash2 size={18} /></button>
                <div className="spacer"></div>
                <button className="icon-btn" title="Star"><Star size={18} className={selectedEmail.starred ? 'starred' : ''} /></button>
                <button className="icon-btn" title="More"><MoreVertical size={18} /></button>
              </div>
              <h2 className="email-viewer-subject">{selectedEmail.subject}</h2>
              <div className="email-viewer-meta">
                <div className="email-viewer-sender">
                  <strong>{selectedEmail.sender}</strong> &lt;sender@example.com&gt;
                </div>
                <div className="email-viewer-date">{selectedEmail.date}</div>
              </div>
            </div>
            
            <div className="email-viewer-body">
              <p>This is a placeholder for the email body content. In the full implementation, this will render HTML securely.</p>
              <br/>
              <p>{selectedEmail.preview}</p>
            </div>

            <div className="email-viewer-footer">
              <button className="secondary-btn"><Reply size={16} /> Reply</button>
              <button className="secondary-btn"><Forward size={16} /> Forward</button>
            </div>
          </div>
        ) : (
          <div className="email-empty">
            <Inbox size={48} />
            <p>Select an email to read</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default EmailPage;
