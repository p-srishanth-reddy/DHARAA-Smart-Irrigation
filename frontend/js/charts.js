// DHARAA Chart.js Integration - Clean Nature-Inspired Light Theme
// Uses centralized color palette: green #22A447, blue #3B82F6, orange #F59E0B

if (window.Chart) {
  Chart.defaults.color = '#4B5563';
  Chart.defaults.font.family = "'Inter', sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.plugins.tooltip.backgroundColor = '#1F2937';
  Chart.defaults.plugins.tooltip.titleColor = '#F9FAFB';
  Chart.defaults.plugins.tooltip.bodyColor = '#F9FAFB';
  Chart.defaults.plugins.tooltip.borderColor = '#E5E7EB';
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 6;
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
        borderColor: '#22A447',
        backgroundColor: 'rgba(34, 164, 71, 0.08)',
        borderWidth: 2,
        fill: true,
        tension: 0.35,
        pointRadius: 2,
        pointHoverRadius: 5,
        pointBackgroundColor: '#22A447'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: {
          min: 0,
          max: 100,
          grid: { color: '#F3F4F6' },
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
          borderColor: '#F59E0B',
          backgroundColor: '#F59E0B',
          yAxisID: 'yTemp',
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 3
        },
        {
          type: 'bar',
          label: 'Precipitation Probability (%)',
          data: rainProbs,
          backgroundColor: 'rgba(59, 130, 246, 0.55)',
          borderColor: '#3B82F6',
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
          grid: { color: '#F3F4F6' },
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
