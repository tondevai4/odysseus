import React, { useState, useRef, useEffect } from 'react';
import { Send, Image as ImageIcon, Paperclip, Mic, ChevronUp } from 'lucide-react';
import './ChatPage.css';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

const CommandCard = ({ index, title, subtitle, desc, btnText }: any) => (
  <div className="flex flex-col p-5 rounded-2xl bg-[#111827]/80 backdrop-blur-md border border-white/5 hover:border-cyan-500/30 transition-all duration-300 shadow-lg shadow-black/20 group cursor-pointer hover:-translate-y-1">
    <div className="flex justify-between items-center mb-3">
      <span className="text-xs font-mono text-cyan-500/50">0{index}</span>
      <span className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">{subtitle}</span>
    </div>
    <h3 className="text-lg font-semibold text-white mb-2">{title}</h3>
    <p className="text-xs text-slate-400 leading-relaxed mb-6 flex-1">{desc}</p>
    <button className="flex items-center gap-2 text-xs font-semibold text-cyan-400 opacity-80 group-hover:opacity-100 transition-opacity mt-auto">
      {btnText} <span className="group-hover:translate-x-1 transition-transform">→</span>
    </button>
  </div>
);

const ChatPage = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;
    setMessages(prev => [...prev, { id: Date.now().toString(), role: 'user', content: input }]);
    setInput('');
    setTimeout(() => {
      setMessages(prev => [...prev, { id: Date.now().toString(), role: 'assistant', content: 'This is the new React frontend connecting to the YVES engine.' }]);
    }, 1000);
  };

  return (
    <div className="relative flex flex-col h-full w-full bg-[#0b0f19]">
      {/* Background Gradient & Noise */}
      <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-cyan-900/10 via-[#0b0f19] to-black z-0"></div>

      <div className="flex-1 overflow-y-auto px-4 md:px-8 pb-32 z-10 scrollbar-hide">
        {messages.length === 0 ? (
          <div className="max-w-4xl mx-auto pt-20 md:pt-32 pb-12 flex flex-col">
            <h1 className="text-5xl md:text-7xl font-bold tracking-tight text-white mb-2 bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">YVES</h1>
            <h2 className="text-2xl md:text-3xl font-semibold text-cyan-400 mb-4">Boss.</h2>
            <p className="text-sm font-mono text-slate-500 tracking-wider mb-16 uppercase">Powered by STRNOS.</p>
            
            <div className="mb-4">
              <span className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">YVES // STRNOS Command System</span>
              <div className="flex justify-between items-center mt-2">
                <h2 className="text-xl font-bold text-white">Command Center</h2>
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                  <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
                  <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest">System Ready</span>
                </div>
              </div>
            </div>

            {/* Responsive Grid that fixes the overlapping issue */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <CommandCard 
                index={1} subtitle="Today" title="Today's Tasks" 
                desc="Turn today's priorities into a simple todo note. Keep the list short, specific, and ready to act on."
                btnText="Open Notes"
              />
              <CommandCard 
                index={2} subtitle="Mission" title="Career / Labouring Mission" 
                desc="Organise labouring opportunities, CSCS progress, carpentry goals, interview preparation, and application follow-ups."
                btnText="Open Mission Notes"
              />
              <CommandCard 
                index={3} subtitle="Manual" title="Money" 
                desc="Use a private note for manual income, bills, and spending checkpoints. No balances or calculations are generated here."
                btnText="Open Money Notes"
              />
              <CommandCard 
                index={4} subtitle="Routine" title="Habits" 
                desc="Create a checklist note for the routines you want to repeat. Start with one habit that moves the day forward."
                btnText="Open Habit Notes"
              />
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto pt-8 flex flex-col gap-6">
            {messages.map((msg) => (
              <div key={msg.id} className={`flex w-full ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] px-5 py-3.5 rounded-2xl ${
                  msg.role === 'user' 
                    ? 'bg-cyan-500/10 border border-cyan-500/20 text-white rounded-br-sm' 
                    : 'bg-[#111827] border border-white/5 text-slate-200 rounded-bl-sm'
                }`}>
                  {msg.content}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>
      
      {/* Absolute positioned input that won't overlap due to pb-32 on container */}
      <div className="absolute bottom-0 left-0 right-0 p-4 md:p-6 bg-gradient-to-t from-[#0b0f19] via-[#0b0f19]/90 to-transparent z-20">
        <div className="max-w-3xl mx-auto flex items-center gap-2 p-2 rounded-2xl bg-[#111827]/80 backdrop-blur-xl border border-white/10 shadow-2xl focus-within:border-cyan-500/50 focus-within:shadow-cyan-500/10 transition-all duration-300">
          <button className="p-2.5 text-slate-400 hover:text-white transition-colors rounded-xl hover:bg-white/5"><Paperclip size={18} /></button>
          
          <input 
            type="text" 
            className="flex-1 bg-transparent border-none text-white text-sm px-2 focus:outline-none placeholder:text-slate-500" 
            placeholder="Message YVES..." 
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          />
          
          <button className="p-2.5 text-slate-400 hover:text-white transition-colors rounded-xl hover:bg-white/5"><Mic size={18} /></button>
          <button 
            className={`p-2.5 rounded-xl transition-all duration-200 ${input.trim() ? 'bg-cyan-500 text-black hover:bg-cyan-400 shadow-lg shadow-cyan-500/25' : 'bg-white/5 text-slate-500'}`}
            onClick={handleSend} 
            disabled={!input.trim()}
          >
            <ChevronUp size={18} strokeWidth={3} />
          </button>
        </div>
        <div className="text-center mt-3">
          <span className="text-[10px] text-slate-500 tracking-wider">Odysseus V3 Framework</span>
        </div>
      </div>
    </div>
  );
};

export default ChatPage;
