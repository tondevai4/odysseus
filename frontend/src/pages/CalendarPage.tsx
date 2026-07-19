import React from 'react';
import { ChevronLeft, ChevronRight, Plus, Calendar as CalendarIcon, Clock } from 'lucide-react';
import './CalendarPage.css';

const CalendarPage = () => {
  return (
    <div className="calendar-page">
      <div className="calendar-sidebar">
        <div className="sidebar-header">
          <button className="primary-btn w-full justify-center"><Plus size={18} /> New Event</button>
        </div>
        <div className="calendar-mini">
          {/* Mini month view placeholder */}
          <div className="mini-month-header">July 2026</div>
          <div className="mini-month-grid">
            {/* Grid items would go here */}
            <div className="mini-day text-muted">S</div><div className="mini-day text-muted">M</div><div className="mini-day text-muted">T</div><div className="mini-day text-muted">W</div><div className="mini-day text-muted">T</div><div className="mini-day text-muted">F</div><div className="mini-day text-muted">S</div>
            {Array.from({length: 31}).map((_, i) => (
              <div key={i} className={`mini-day ${i+1 === 9 ? 'today' : ''}`}>{i + 1}</div>
            ))}
          </div>
        </div>
        
        <div className="calendars-list">
          <h3>My Calendars</h3>
          <label className="cal-item"><input type="checkbox" defaultChecked /> <span className="cal-color" style={{background: 'var(--brand-color)'}}></span> Personal</label>
          <label className="cal-item"><input type="checkbox" defaultChecked /> <span className="cal-color" style={{background: 'var(--red)'}}></span> Work</label>
          <label className="cal-item"><input type="checkbox" defaultChecked /> <span className="cal-color" style={{background: 'var(--warn)'}}></span> Odysseus Tasks</label>
        </div>
      </div>

      <div className="calendar-main">
        <div className="calendar-header">
          <div className="cal-header-left">
            <button className="secondary-btn">Today</button>
            <div className="cal-nav">
              <button className="icon-btn"><ChevronLeft size={20} /></button>
              <button className="icon-btn"><ChevronRight size={20} /></button>
            </div>
            <h2>July 2026</h2>
          </div>
          <div className="cal-header-right">
            <select className="secondary-btn">
              <option>Month</option>
              <option>Week</option>
              <option>Day</option>
            </select>
          </div>
        </div>

        <div className="calendar-grid-container">
          <div className="calendar-grid-header">
            <div>Sun</div><div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div><div>Sat</div>
          </div>
          <div className="calendar-grid-body">
            {/* 35 day slots for a month view */}
            {Array.from({length: 35}).map((_, i) => (
              <div key={i} className="cal-day-cell">
                <span className={`cal-date-number ${i === 12 ? 'today' : ''}`}>{(i % 31) + 1}</span>
                {i === 12 && (
                  <div className="cal-event" style={{background: 'rgba(0, 229, 255, 0.2)', borderLeft: '3px solid var(--brand-color)'}}>
                    <span className="event-time">10:00a</span> Standup
                  </div>
                )}
                {i === 15 && (
                  <div className="cal-event" style={{background: 'rgba(255, 42, 95, 0.2)', borderLeft: '3px solid var(--red)'}}>
                    <span className="event-time">2:30p</span> React Migration Sync
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default CalendarPage;
