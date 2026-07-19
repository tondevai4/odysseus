import React, { useState } from 'react';
import { Upload, FolderPlus, Image as ImageIcon, MoreHorizontal, Filter } from 'lucide-react';
import './GalleryPage.css';

const GalleryPage = () => {
  return (
    <div className="gallery-page">
      <div className="gallery-header">
        <div className="gallery-header-left">
          <h2>Gallery</h2>
          <div className="gallery-tabs">
            <button className="tab active">All Images</button>
            <button className="tab">Albums</button>
            <button className="tab">AI Generations</button>
          </div>
        </div>
        
        <div className="gallery-actions">
          <button className="icon-btn"><Filter size={18} /></button>
          <button className="icon-btn"><FolderPlus size={18} /></button>
          <button className="primary-btn"><Upload size={18} /> Upload</button>
        </div>
      </div>

      <div className="gallery-content">
        <div className="gallery-empty-state">
          <div className="empty-icon-wrapper">
            <ImageIcon size={48} />
          </div>
          <h3>No images yet</h3>
          <p>Upload images or use the AI generator to create some.</p>
          <button className="primary-btn mt-4"><Upload size={18} /> Upload Image</button>
        </div>
        
        {/* Placeholder for grid when images exist */}
        {/*
        <div className="image-grid">
          <div className="image-card">
            <img src="..." alt="..." />
            <div className="image-overlay">
              <span>image_name.png</span>
              <button><MoreHorizontal size={16} /></button>
            </div>
          </div>
        </div>
        */}
      </div>
    </div>
  );
};

export default GalleryPage;
