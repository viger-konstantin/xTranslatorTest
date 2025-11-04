async function fetchGames() {
  const response = await fetch('/api/games');
  if (!response.ok) {
    throw new Error('Не удалось загрузить список игр');
  }
  return await response.json();
}

function fillSelect(select, games) {
  select.innerHTML = '';
  games.forEach((game) => {
    const option = document.createElement('option');
    option.value = game;
    option.textContent = game;
    select.append(option);
  });
}

function showStatus(message, isError = false) {
  const status = document.getElementById('status');
  status.textContent = message;
  status.classList.toggle('error', isError);
}

async function submitForm(form, url) {
  const data = new FormData(form);
  const response = await fetch(url, {
    method: 'POST',
    body: data,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const message = detail?.detail || 'Сервер вернул ошибку';
    throw new Error(message);
  }
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition');
  let filename = 'result';
  if (disposition) {
    const match = disposition.match(/filename="(.+)"/);
    if (match) {
      filename = match[1];
    }
  }
  const urlObject = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = urlObject;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(urlObject);
}

async function init() {
  try {
    const games = await fetchGames();
    const extractSelect = document.getElementById('extract-game');
    const applySelect = document.getElementById('apply-game');
    if (games.length === 0) {
      throw new Error('Не найдены папки с описаниями игр в каталоге Data.');
    }
    fillSelect(extractSelect, games);
    fillSelect(applySelect, games);
  } catch (error) {
    showStatus(error.message, true);
  }

  document.getElementById('extract-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    showStatus('Формируем Excel...');
    try {
      await submitForm(event.target, '/api/extract');
      showStatus('Готово! Файл скачан.');
    } catch (error) {
      showStatus(error.message, true);
    }
  });

  document.getElementById('apply-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    showStatus('Собираем обновлённый ESP...');
    try {
      await submitForm(event.target, '/api/apply');
      showStatus('Готово! Файл скачан.');
    } catch (error) {
      showStatus(error.message, true);
    }
  });
}

init();
