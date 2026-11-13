import { loadTeacher } from './teacher';

declare global {
  interface Window {
    loadTeacher: typeof loadTeacher;
  }
}
window.loadTeacher = loadTeacher;
