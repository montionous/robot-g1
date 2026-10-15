'use strict';

const form = document.querySelector('#login-form');
const password = document.querySelector('#password');
const toggle = document.querySelector('#toggle-password');
const submit = document.querySelector('#login-submit');
const errorMessage = document.querySelector('#login-error');
let submitting = false;

toggle.addEventListener('click', () => {
  const showing = password.type === 'password';
  password.type = showing ? 'text' : 'password';
  toggle.setAttribute('aria-label', showing ? '隐藏密码' : '显示密码');
  toggle.setAttribute('aria-pressed', String(showing));
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submitting) return;
  submitting = true;
  submit.disabled = true;
  submit.firstElementChild.textContent = '正在登录…';
  errorMessage.textContent = '';
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Care-Console': '1'},
      body: JSON.stringify({username: form.elements.username.value.trim(), password: password.value}),
      signal: AbortSignal.timeout(10000),
    });
    if (response.status === 429) throw new Error('登录尝试较多，请稍后再试。');
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '登录暂时不可用，请稍后再试。');
    password.value = '';
    location.replace('/');
  } catch (error) {
    errorMessage.textContent = error.name === 'TimeoutError' || error instanceof TypeError
      ? '连接未完成，请检查网络后重试。' : error.message;
  } finally {
    submitting = false;
    submit.disabled = false;
    submit.firstElementChild.textContent = '登录工作台';
  }
});
