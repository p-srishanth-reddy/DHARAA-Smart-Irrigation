// DHARAA Frontend API & Utility Layer

const API = {
  async get(endpoint) {
    try {
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error(`GET ${endpoint} failed:`, err);
      throw err;
    }
  },

  async post(endpoint, data = {}) {
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP error ${res.status}`);
      }
      return await res.json();
    } catch (err) {
      console.error(`POST ${endpoint} failed:`, err);
      throw err;
    }
  },

  async put(endpoint, data = {}) {
    try {
      const res = await fetch(endpoint, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await res.json();
    } catch (err) {
      console.error(`PUT ${endpoint} failed:`, err);
      throw err;
    }
  },

  async delete(endpoint) {
    try {
      const res = await fetch(endpoint, { method: 'DELETE' });
      return await res.json();
    } catch (err) {
      console.error(`DELETE ${endpoint} failed:`, err);
      throw err;
    }
  }
};

// UI Notifications & Toasts
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  const icon = type === 'success' ? '✓' : (type === 'error' ? '⚠️' : 'ℹ️');
  const color = type === 'success' ? '#10b981' : (type === 'error' ? '#f43f5e' : '#06b6d4');
  
  toast.style.borderColor = color;
  toast.innerHTML = `<span style="color: ${color}; font-weight: bold; font-size: 1.1rem;">${icon}</span> <span>${message}</span>`;
  
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(100%)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
