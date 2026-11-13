import { mount } from 'svelte';
import App from './App.svelte';

const target = document.getElementById('app');
if (target === null) {
  throw new Error('The application root #app is missing from index.html.');
}

mount(App, { target });
