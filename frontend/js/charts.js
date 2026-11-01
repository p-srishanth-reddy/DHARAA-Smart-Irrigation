// DHARAA Chart.js Integration

// Chart.js global dark theme defaults
if (window.Chart) {
  Chart.defaults.color = '#94a3b8';
  Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";
  Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(15, 23, 42, 0.9)';
  Chart.defaults.plugins.tooltip.borderColor = 'rgba(255, 255, 255, 0.1)';
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.padding = 12;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
}

function createMoistureChart(canvasId, historyData = []) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  const labels = historyData.map(d => d.timestamp ? d.timestamp.split(' ')[1] : '');
  const moistures = historyData.map(d => d.moisture);

  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Soil Moisture (%)',
        data: moistures,
        borderColor: '#10b981',
        backgroundColor: 'rgba(16, 185, 129, 0.12)',
        borderWidth: 2.5,
        fill: true,
        tension: 0.4,
        pointRadius: 2,
        pointHoverRadius: 6,
        pointBackgroundColor: '#10b981'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          min: 0,
          max: 100,
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { callback: v => v + '%' }
        },
        x: {
          grid: { display: false }
        }
      },
      plugins: {
        legend: { display: false }
      }
    }
  });
}

function createWeatherForecastChart(canvasId, times, temps, rainProbs) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;

  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels: times.map(t => t.includes('T') ? t.split('T')[1].substring(0, 5) : t),
      datasets: [
        {
          type: 'line',
          label: 'Temperature (°C)',
          data: temps,
          borderColor: '#f59e0b',
          backgroundColor: '#f59e0b',
          yAxisID: 'yTemp',
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 3
        },
        {
          type: 'bar',
          label: 'Precipitation Probability (%)',
          data: rainProbs,
          backgroundColor: 'rgba(6, 182, 212, 0.45)',
          borderColor: '#06b6d4',
          borderWidth: 1,
          borderRadius: 4,
          yAxisID: 'yRain'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        yTemp: {
          type: 'linear',
          position: 'left',
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { callback: v => v + '°C' }
        },
        yRain: {
          type: 'linear',
          position: 'right',
          min: 0,
          max: 100,
          grid: { display: false },
          ticks: { callback: v => v + '%' }
        },
        x: {
          grid: { display: false }
        }
      }
    }
  });
}
