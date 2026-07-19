import React, { useState } from 'react';
import { Plus, CheckCircle2, Circle, Clock, Play, MoreVertical } from 'lucide-react';
import './TasksPage.css';

interface Task {
  id: string;
  title: string;
  schedule: string;
  lastRun: string;
  status: 'active' | 'completed' | 'failed';
}

const TasksPage = () => {
  const [tasks] = useState<Task[]>([
    { id: '1', title: 'Daily backup to Vault', schedule: '0 2 * * * (Every day at 2:00 AM)', lastRun: 'Today at 2:00 AM', status: 'completed' },
    { id: '2', title: 'Fetch latest news', schedule: '0 8 * * * (Every day at 8:00 AM)', lastRun: 'Today at 8:00 AM', status: 'completed' },
    { id: '3', title: 'Summarize unread emails', schedule: 'Manual', lastRun: 'Never', status: 'active' },
  ]);

  return (
    <div className="tasks-page">
      <div className="tasks-header">
        <h2>Scheduled Tasks</h2>
        <button className="primary-btn"><Plus size={18} /> Create Task</button>
      </div>

      <div className="tasks-content">
        <div className="tasks-list">
          {tasks.map(task => (
            <div key={task.id} className="task-card">
              <div className="task-header">
                <div className="task-title-group">
                  {task.status === 'completed' ? (
                    <CheckCircle2 size={20} className="text-success" />
                  ) : (
                    <Circle size={20} className="text-muted" />
                  )}
                  <h3 className="task-title">{task.title}</h3>
                </div>
                <div className="task-actions">
                  <button className="icon-btn" title="Run Now"><Play size={18} /></button>
                  <button className="icon-btn"><MoreVertical size={18} /></button>
                </div>
              </div>
              
              <div className="task-details">
                <div className="task-detail-item">
                  <Clock size={16} />
                  <span>Schedule: {task.schedule}</span>
                </div>
                <div className="task-detail-item text-muted">
                  <span>Last run: {task.lastRun}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default TasksPage;
