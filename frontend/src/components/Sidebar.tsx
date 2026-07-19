import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { 
  MessageSquare, LayoutTemplate, PenTool, Image, Mail, Calendar, 
  CheckSquare, Database, Search, PlusCircle, Monitor, BookOpen, User
} from 'lucide-react';
import './Sidebar.css';

const SidebarSection = ({ title, icon: Icon, children }: { title: string, icon: any, children: React.ReactNode }) => {
  const [collapsed, setCollapsed] = useState(false);
  
  return (
    <div className="mt-2 mb-3">
      <div 
        className="flex items-center gap-2 px-2 py-2 mx-1 rounded-md cursor-pointer transition-colors duration-150 hover:bg-white/5"
        onClick={() => setCollapsed(!collapsed)}
      >
        <Icon className="w-3 h-3 text-cyan-400 opacity-80" />
        <span className="flex-1 text-[11px] font-bold uppercase tracking-widest text-slate-300">
          {title}
        </span>
        <svg 
          className={`w-3 h-3 text-slate-500 transition-transform duration-200 ${collapsed ? '-rotate-90' : ''}`} 
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>
      <div className={`overflow-hidden transition-all duration-300 ${collapsed ? 'max-h-0 opacity-0' : 'max-h-[1000px] opacity-100'}`}>
        {children}
      </div>
    </div>
  );
};

const Sidebar = () => {
  return (
    <nav className="flex flex-col w-[260px] h-full border-r border-white/10 bg-[#0b0f19]/80 backdrop-blur-xl shrink-0 z-50">
      <div className="flex items-center gap-3 px-6 py-5 min-h-[48px] shrink-0">
        <span className="text-xl font-bold tracking-wide text-cyan-400">YVES</span>
      </div>
      
      <div className="flex-1 overflow-y-auto px-2 pb-4 scrollbar-hide">
        {/* Core Actions */}
        <div className="mb-4">
          <NavLink to="/" className="flex items-center gap-3 px-3 py-2.5 mx-1 mb-1 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-all duration-200 shadow-sm hover:shadow-cyan-500/10 hover:-translate-y-[1px]">
            <PlusCircle className="w-5 h-5 text-cyan-400" />
            <span className="text-sm font-semibold text-cyan-400">New Chat</span>
          </NavLink>
          <div className="flex items-center gap-3 px-3 py-2.5 mx-1 mb-1 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-all duration-200 shadow-sm">
            <Monitor className="w-4 h-4 text-slate-300" />
            <span className="text-sm font-medium text-slate-200">Command Center</span>
          </div>
          <div className="flex items-center gap-3 px-3 py-2.5 mx-1 mb-1 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-all duration-200 shadow-sm">
            <Search className="w-4 h-4 text-slate-300" />
            <span className="text-sm font-medium text-slate-200">Search</span>
          </div>
        </div>

        {/* Primary Views */}
        <SidebarSection title="Conversations" icon={MessageSquare}>
          <NavLink to="/" className={({isActive}) => `flex items-center gap-3 px-3 py-2 mx-1 rounded-md transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`} end>
            <MessageSquare className="w-4 h-4 opacity-50" />
            <span className="text-sm">Chats</span>
          </NavLink>
          <NavLink to="/email" className={({isActive}) => `flex items-center gap-3 px-3 py-2 mx-1 rounded-md transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}>
            <Mail className="w-4 h-4 opacity-50" />
            <span className="text-sm">Email</span>
          </NavLink>
        </SidebarSection>

        {/* Productivity */}
        <SidebarSection title="Productivity" icon={Calendar}>
          <NavLink to="/calendar" className={({isActive}) => `flex items-center gap-3 px-3 py-2 mx-1 rounded-md transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}>
            <Calendar className="w-4 h-4 opacity-50" />
            <span className="text-sm">Calendar</span>
          </NavLink>
          <NavLink to="/tasks" className={({isActive}) => `flex items-center gap-3 px-3 py-2 mx-1 rounded-md transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}>
            <CheckSquare className="w-4 h-4 opacity-50" />
            <span className="text-sm">Tasks</span>
          </NavLink>
          <NavLink to="/documents" className={({isActive}) => `flex items-center gap-3 px-3 py-2 mx-1 rounded-md transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}>
            <PenTool className="w-4 h-4 opacity-50" />
            <span className="text-sm">Notes</span>
          </NavLink>
          <NavLink to="/gallery" className={({isActive}) => `flex items-center gap-3 px-3 py-2 mx-1 rounded-md transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}>
            <Image className="w-4 h-4 opacity-50" />
            <span className="text-sm">Gallery</span>
          </NavLink>
        </SidebarSection>

        {/* System & AI */}
        <SidebarSection title="System & AI" icon={Database}>
          <NavLink to="/cookbook" className={({isActive}) => `flex items-center gap-3 px-3 py-2 mx-1 rounded-md transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}>
            <Database className="w-4 h-4 opacity-50" />
            <span className="text-sm">Cookbook</span>
          </NavLink>
          <NavLink to="/settings" className={({isActive}) => `flex items-center gap-3 px-3 py-2 mx-1 rounded-md transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5 hover:text-white'}`}>
            <LayoutTemplate className="w-4 h-4 opacity-50" />
            <span className="text-sm">Settings</span>
          </NavLink>
        </SidebarSection>

        {/* Personal */}
        <SidebarSection title="Personal" icon={BookOpen}>
          <div className="flex items-center gap-3 px-3 py-2 mx-1 rounded-md text-slate-300 hover:bg-white/5 hover:text-white transition-colors cursor-pointer">
            <BookOpen className="w-4 h-4 opacity-50" />
            <span className="text-sm">Reading List</span>
          </div>
        </SidebarSection>
      </div>

      <div className="relative p-4 mt-auto border-t border-white/10 bg-gradient-to-t from-black/20 to-transparent">
        <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-white/5 border border-transparent hover:bg-white/10 hover:border-white/10 hover:shadow-lg hover:shadow-cyan-500/10 cursor-pointer transition-all duration-200">
          <div className="flex items-center justify-center w-9 h-9 rounded-full bg-cyan-500/20 text-cyan-400 font-bold text-sm border border-cyan-500/30">
            US
          </div>
          <span className="font-semibold text-sm text-slate-200">User</span>
        </div>
      </div>
    </nav>
  );
};

export default Sidebar;
