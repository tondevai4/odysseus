import React, { useState } from 'react';
import { FileText, Plus, Search, MoreVertical, Save, History, Sparkles } from 'lucide-react';
import './DocumentsPage.css';

interface Document {
  id: string;
  title: string;
  updatedAt: string;
}

const DocumentsPage = () => {
  const [documents] = useState<Document[]>([
    { id: '1', title: 'Project Proposal', updatedAt: '2 hours ago' },
    { id: '2', title: 'Meeting Notes', updatedAt: 'Yesterday' },
    { id: '3', title: 'Odysseus V3 Plan', updatedAt: '3 days ago' },
  ]);
  const [activeDoc, setActiveDoc] = useState<string>('1');

  return (
    <div className="documents-page">
      <div className="documents-sidebar">
        <div className="docs-sidebar-header">
          <h2>Documents</h2>
          <button className="icon-btn primary"><Plus size={18} /></button>
        </div>
        
        <div className="docs-search">
          <Search size={16} className="search-icon" />
          <input type="text" placeholder="Search documents..." />
        </div>

        <div className="docs-list">
          {documents.map(doc => (
            <div 
              key={doc.id} 
              className={`doc-item ${activeDoc === doc.id ? 'active' : ''}`}
              onClick={() => setActiveDoc(doc.id)}
            >
              <FileText size={18} className="doc-icon" />
              <div className="doc-info">
                <span className="doc-title">{doc.title}</span>
                <span className="doc-date">{doc.updatedAt}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="documents-editor-area">
        <div className="editor-header">
          <input 
            type="text" 
            className="editor-title-input" 
            defaultValue={documents.find(d => d.id === activeDoc)?.title || 'Untitled Document'} 
          />
          <div className="editor-actions">
            <button className="text-btn"><Sparkles size={16} /> AI Edit</button>
            <button className="icon-btn"><History size={18} /></button>
            <button className="icon-btn"><Save size={18} /></button>
            <button className="icon-btn"><MoreVertical size={18} /></button>
          </div>
        </div>

        <div className="editor-content-wrapper">
          <textarea 
            className="editor-textarea"
            placeholder="Start writing..."
            defaultValue={activeDoc === '1' ? "# Project Proposal\n\nThis is a sample document body. In the full implementation, this will use a rich text editor like Tiptap or a markdown editor like Monaco/CodeMirror." : ""}
          />
        </div>
      </div>
    </div>
  );
};

export default DocumentsPage;
