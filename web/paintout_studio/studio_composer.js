const svg=body=>`<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
export const composerIcons={
  video:svg('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m10 9 5 3-5 3z"/>'),
  image:svg('<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1"/><path d="m3 16 6-6 6 6 3-3 3 3"/>'),
  model:svg('<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>'),
  size:svg('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h4M7 9v4m10 2h-4m4 0v-4"/>'),
  clock:svg('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'),
  audio:svg('<path d="M4 10v4m4-7v10m4-13v16m4-13v10m4-7v4"/>'),
  settings:svg('<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="var(--zc-composer)"/><circle cx="15" cy="17" r="3" fill="var(--zc-composer)"/>'),
  chevron:svg('<path d="m8 10 4 4 4-4"/>'),
  trim:svg('<path d="M6 3v12a3 3 0 0 0 3 3h12M3 6h12a3 3 0 0 1 3 3v12"/>'),
  view:svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  compare:svg('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16M6 9h3m-3 6h3m6-6h3m-3 6h3"/>'),
  history:svg('<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6M12 7v5l3 2"/>'),
  takes:svg('<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M7 3h10m-8 9 6 3-6 3z"/>'),
  download:svg('<path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4"/>'),
};
