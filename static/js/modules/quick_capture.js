// static/js/modules/quick_capture.js
/**
 * Global Quick Capture & Spotlight Modal for YVES.
 * Activated via Cmd+K / Ctrl+Space with smart intent routing and instant voice dump.
 */

const QuickCapture = {
  isOpen: false,
  mediaRecorder: null,
  audioChunks: [],
  isRecording: false,

  init() {
    console.log('[QuickCapture] Initializing global spotlight overlay...');
    this.createModalDOM();
    this.bindKeyboardShortcuts();
  },

  createModalDOM() {
    if (document.getElementById('quick-capture-root')) return;

    const modalWrap = document.createElement('div');
    modalWrap.id = 'quick-capture-root';
    modalWrap.className = 'quick-capture-backdrop';
    modalWrap.style.display = 'none';

    modalWrap.innerHTML = `
      <div class="quick-capture-modal">
        <div class="quick-capture-header">
          <div class="quick-capture-badge" id="qc-target-badge">Agent Query</div>
          <span class="quick-capture-hint">ESC to close</span>
        </div>
        <div class="quick-capture-input-wrap">
          <input 
            type="text" 
            id="qc-input" 
            class="quick-capture-input" 
            placeholder="Type anything or press mic (e.g. 'Bench press 80kg 3x8', 'Remind me tomorrow', or chat)..." 
            autocomplete="off"
          />
          <button id="qc-mic-btn" class="quick-capture-mic" title="Voice Dump">🎤</button>
        </div>
        <div class="quick-capture-footer">
          <span id="qc-status">Press Enter to execute</span>
          <button id="qc-submit-btn" class="quick-capture-submit">Run ↵</button>
        </div>
      </div>
    `;

    document.body.appendChild(modalWrap);

    // Event listeners
    const input = document.getElementById('qc-input');
    input.addEventListener('input', () => this.updateRoutingBadge(input.value));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.submitAction();
      }
    });

    document.getElementById('qc-submit-btn').addEventListener('click', () => this.submitAction());
    document.getElementById('qc-mic-btn').addEventListener('click', () => this.toggleVoiceRecording());

    modalWrap.addEventListener('click', (e) => {
      if (e.target === modalWrap) this.close();
    });
  },

  bindKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Cmd + K or Ctrl + Space or Ctrl + K
      const isCmdK = (e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K');
      const isCtrlSpace = e.ctrlKey && e.code === 'Space';

      if (isCmdK || isCtrlSpace) {
        e.preventDefault();
        this.toggle();
      } else if (e.key === 'Escape' && this.isOpen) {
        this.close();
      }
    });
  },

  toggle() {
    if (this.isOpen) this.close();
    else this.open();
  },

  open() {
    this.isOpen = true;
    const modalWrap = document.getElementById('quick-capture-root');
    if (modalWrap) {
      modalWrap.style.display = 'flex';
      const input = document.getElementById('qc-input');
      if (input) {
        input.value = '';
        this.updateRoutingBadge('');
        setTimeout(() => input.focus(), 50);
      }
    }
  },

  close() {
    this.isOpen = false;
    const modalWrap = document.getElementById('quick-capture-root');
    if (modalWrap) modalWrap.style.display = 'none';
    if (this.isRecording) this.stopVoiceRecording();
  },

  updateRoutingBadge(text) {
    const badge = document.getElementById('qc-target-badge');
    if (!badge) return;

    const low = text.trim().lower ? text.trim().toLowerCase() : '';
    if (!low) {
      badge.textContent = 'Agent Query';
      badge.className = 'quick-capture-badge badge-neutral';
      return;
    }

    if (/\b(bench|squat|deadlift|overhead|curl|workout|reps|kg|rpe)\b/.test(low)) {
      badge.textContent = '[Logged to Gym]';
      badge.className = 'quick-capture-badge badge-gym';
    } else if (/\b(remind|todo|task|schedule|due)\b/.test(low)) {
      badge.textContent = '[Saved to Tasks]';
      badge.className = 'quick-capture-badge badge-task';
    } else if (/\b(note:|memo:|remember)\b/.test(low)) {
      badge.textContent = '[Saved to Notes]';
      badge.className = 'quick-capture-badge badge-note';
    } else {
      badge.textContent = '[Agent Chat]';
      badge.className = 'quick-capture-badge badge-agent';
    }
  },

  async submitAction() {
    const input = document.getElementById('qc-input');
    const status = document.getElementById('qc-status');
    const text = input ? input.value.trim() : '';
    if (!text) return;

    const low = text.toLowerCase();
    status.textContent = 'Executing...';

    try {
      // 1. Route to Gym
      if (/\b(bench|squat|deadlift|overhead|press|reps|kg)\b/.test(low)) {
        const weightMatch = text.match(/(\d+(?:\.\d+)?)\s*kg/i) || text.match(/(\d+(?:\.\d+)?)/);
        const repsMatch = text.match(/(\d+)\s*(?:reps|x)/i);
        const weight = weightMatch ? parseFloat(weightMatch[1]) : 50.0;
        const reps = repsMatch ? parseInt(repsMatch[1], 10) : 5;

        await fetch('/api/gym/workout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            exercise: text.split(/\d/)[0].trim() || 'Workout Set',
            sets: 1,
            reps: reps,
            weight_kg: weight,
            notes: text,
          }),
        });
        status.textContent = 'Logged to Gym successfully!';
      } else {
        // Default: send to main chat composer or trigger agent query
        const chatInput = document.getElementById('user-input') || document.querySelector('textarea.chat-input');
        if (chatInput) {
          chatInput.value = text;
          const sendBtn = document.getElementById('send-btn') || document.querySelector('.send-button');
          if (sendBtn) sendBtn.click();
        }
        status.textContent = 'Dispatched to YVES!';
      }

      setTimeout(() => this.close(), 600);
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  },

  async toggleVoiceRecording() {
    if (this.isRecording) {
      this.stopVoiceRecording();
    } else {
      await this.startVoiceRecording();
    }
  },

  async startVoiceRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.mediaRecorder = new MediaRecorder(stream);
      this.audioChunks = [];

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.audioChunks.push(e.data);
      };

      this.mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
        const formData = new FormData();
        formData.append('file', audioBlob, 'quick_dump.wav');

        const status = document.getElementById('qc-status');
        if (status) status.textContent = 'Transcribing voice...';

        try {
          const res = await fetch('/api/stt', { method: 'POST', body: formData });
          if (res.ok) {
            const data = await res.json();
            const input = document.getElementById('qc-input');
            if (input && data.text) {
              input.value = data.text;
              this.updateRoutingBadge(data.text);
            }
          }
        } catch (e) {
          console.debug('STT upload error:', e);
        }
        if (status) status.textContent = 'Press Enter to execute';
      };

      this.mediaRecorder.start();
      this.isRecording = true;
      const micBtn = document.getElementById('qc-mic-btn');
      if (micBtn) micBtn.classList.add('recording-active');
    } catch (e) {
      alert('Microphone access unavailable');
    }
  },

  stopVoiceRecording() {
    if (this.mediaRecorder && this.isRecording) {
      this.mediaRecorder.stop();
      this.isRecording = false;
      const micBtn = document.getElementById('qc-mic-btn');
      if (micBtn) micBtn.classList.remove('recording-active');
    }
  },
};

export default QuickCapture;
