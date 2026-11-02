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

const FarmSelection = {
  storageKey: 'dharaa_selected_farm_id',
  eventName: 'dharaa:farm-selection-change',

  getId() {
    const id = Number(localStorage.getItem(this.storageKey));
    return Number.isSafeInteger(id) && id > 0 ? id : null;
  },

  setId(id, notify = true) {
    const farmId = Number(id);
    if (!Number.isSafeInteger(farmId) || farmId <= 0) {
      throw new Error('A valid farm ID is required.');
    }

    const changed = this.getId() !== farmId;
    localStorage.setItem(this.storageKey, String(farmId));
    if (changed && notify) {
      window.dispatchEvent(new CustomEvent(this.eventName, { detail: { farmId } }));
    }
  },

  resolve(farms, preferredId = null) {
    const preferredFarmId = Number(preferredId);
    const preferredFarm = Number.isSafeInteger(preferredFarmId) && preferredFarmId > 0
      ? farms.find(item => item.id === preferredFarmId)
      : null;
    const storedFarmId = this.getId();
    const farm = preferredFarm
      || farms.find(item => item.id === storedFarmId)
      || farms[0]
      || null;
    if (farm) this.setId(farm.id, false);
    return farm;
  },

  onChange(callback) {
    window.addEventListener(this.eventName, event => callback(event.detail.farmId));
    window.addEventListener('storage', event => {
      if (event.key === this.storageKey && event.newValue) {
        callback(Number(event.newValue));
      }
    });
  }
};

async function loadSelectedFarm(preferredId = null) {
  const farms = await API.get('/api/farms');
  const farm = FarmSelection.resolve(farms, preferredId);
  if (!farm) throw new Error('No farms are available. Add a farm before continuing.');
  return farm;
}

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
  
  const icon = type === 'success' ? '✓' : (type === 'error' ? '✕' : (type === 'warning' ? '⚠' : 'ℹ'));
  
  toast.innerHTML = `<span style="font-weight: 700; font-size: 1rem;">${icon}</span> <span>${message}</span>`;
  
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
    setTimeout(() => toast.remove(), 200);
  }, 4000);
}

// Mobile Sidebar Drawer Toggle Helper
document.addEventListener("DOMContentLoaded", () => {
  const btnMobile = document.getElementById('btn-mobile-menu');
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.querySelector('.sidebar-overlay');

  if (btnMobile && sidebar) {
    btnMobile.addEventListener('click', () => {
      sidebar.classList.toggle('mobile-open');
      if (overlay) overlay.classList.toggle('mobile-open');
    });
  }

  if (overlay && sidebar) {
    overlay.addEventListener('click', () => {
      sidebar.classList.remove('mobile-open');
      overlay.classList.remove('mobile-open');
    });
  }
});
