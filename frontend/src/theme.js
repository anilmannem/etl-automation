import { createTheme } from '@mui/material/styles';

const PRIMARY = '#3171D6';
const PRIMARY_LIGHT = '#5B9AE8';
const PRIMARY_DARK = '#1D55B0';
const TEAL = '#0D9488';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: PRIMARY, light: PRIMARY_LIGHT, dark: PRIMARY_DARK },
    secondary: { main: TEAL, light: '#2DD4BF', dark: '#0F766E' },
    error: { main: '#E11D48', light: '#FDA4AF', dark: '#9F1239' },
    warning: { main: '#D97706', light: '#FCD34D', dark: '#92400E' },
    success: { main: TEAL, light: '#5EEAD4', dark: '#0F766E' },
    background: { default: '#EEF2FA', paper: '#FFFFFF' },
    text: { primary: '#0F172A', secondary: '#475569', disabled: '#94A3B8' },
    divider: 'rgba(15,23,42,0.07)',
  },
  typography: {
    fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h1: { fontWeight: 800, fontSize: '2rem', letterSpacing: '-0.03em', lineHeight: 1.2 },
    h2: { fontWeight: 700, fontSize: '1.5rem', letterSpacing: '-0.02em', lineHeight: 1.3 },
    h3: { fontWeight: 700, fontSize: '1.25rem', letterSpacing: '-0.01em' },
    h4: { fontWeight: 600, fontSize: '1.1rem', letterSpacing: '-0.01em' },
    h5: { fontWeight: 600, fontSize: '0.975rem' },
    h6: { fontWeight: 600, fontSize: '0.875rem' },
    body1: { fontSize: '0.875rem', lineHeight: 1.65 },
    body2: { fontSize: '0.8125rem', lineHeight: 1.6 },
    caption: { fontSize: '0.75rem', lineHeight: 1.5 },
    overline: { fontSize: '0.625rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase' },
    button: { textTransform: 'none', fontWeight: 600, fontSize: '0.875rem', letterSpacing: '0' },
  },
  shape: { borderRadius: 10 },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { backgroundColor: '#EEF2FA' },
        '*': { scrollbarWidth: 'thin', scrollbarColor: 'rgba(148,163,184,0.4) transparent' },
        '::-webkit-scrollbar': { width: 6, height: 6 },
        '::-webkit-scrollbar-track': { background: 'transparent' },
        '::-webkit-scrollbar-thumb': { background: 'rgba(148,163,184,0.4)', borderRadius: 4 },
        '::-webkit-scrollbar-thumb:hover': { background: 'rgba(148,163,184,0.7)' },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: { borderRadius: 8, padding: '8px 18px', boxShadow: 'none', fontWeight: 600, '&:hover': { boxShadow: 'none' } },
        contained: {
          background: `linear-gradient(135deg, ${PRIMARY} 0%, ${PRIMARY_LIGHT} 100%)`,
          color: '#fff',
          '&:hover': { background: `linear-gradient(135deg, ${PRIMARY_DARK} 0%, ${PRIMARY} 100%)` },
          '&.Mui-disabled': { background: '#E2E8F0', color: '#94A3B8' },
        },
        outlined: { borderColor: 'rgba(15,23,42,0.15)', '&:hover': { borderColor: PRIMARY } },
        text: { '&:hover': { backgroundColor: 'rgba(15,23,42,0.04)' } },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid rgba(15,23,42,0.07)',
          boxShadow: '0 1px 3px rgba(15,23,42,0.04), 0 6px 20px rgba(15,23,42,0.06)',
          borderRadius: 16,
        },
      },
    },
    MuiDrawer: {
      styleOverrides: { paper: { border: 'none', boxShadow: '1px 0 0 rgba(15,23,42,0.07)', borderRadius: 0 } },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontWeight: 600, fontSize: '0.72rem', height: 24 },
        sizeSmall: { height: 22, fontSize: '0.68rem' },
      },
    },
    MuiTextField: {
      defaultProps: { variant: 'outlined' },
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: 8,
            backgroundColor: '#FAFBFC',
            transition: 'box-shadow 0.15s',
            '& fieldset': { borderColor: 'rgba(15,23,42,0.14)' },
            '&:hover fieldset': { borderColor: 'rgba(15,23,42,0.25)' },
            '&.Mui-focused': { backgroundColor: '#fff', boxShadow: `0 0 0 3px rgba(49,113,214,0.12)` },
            '&.Mui-focused fieldset': { borderColor: PRIMARY },
          },
          '& .MuiInputLabel-root.Mui-focused': { color: PRIMARY },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderColor: 'rgba(15,23,42,0.06)', padding: '10px 14px', fontSize: '0.8125rem' },
        head: { fontWeight: 600, color: '#64748B', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', backgroundColor: '#F8FAFC' },
        stickyHeader: { backgroundColor: '#F8FAFC' },
      },
    },
    MuiTableRow: {
      styleOverrides: { root: { '&:hover': { backgroundColor: 'rgba(49,113,214,0.025)' } } },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: { backgroundColor: '#1E293B', borderRadius: 6, fontSize: '0.75rem', padding: '6px 10px' },
        arrow: { color: '#1E293B' },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 8, fontSize: '0.8125rem' },
        standardError: { backgroundColor: '#FFF1F2', color: '#881337', border: '1px solid #FECDD3' },
        standardSuccess: { backgroundColor: '#F0FDF9', color: '#065F46', border: '1px solid #99F6E4' },
        standardInfo: { backgroundColor: '#EFF6FF', color: '#1E3A8A', border: '1px solid #BFDBFE' },
        standardWarning: { backgroundColor: '#FFFBEB', color: '#78350F', border: '1px solid #FDE68A' },
      },
    },
    MuiSwitch: {
      styleOverrides: {
        track: { borderRadius: 10, opacity: 1, backgroundColor: '#CBD5E1' },
        switchBase: { '&.Mui-checked': { '& + .MuiSwitch-track': { backgroundColor: PRIMARY, opacity: 1 } } },
      },
    },
    MuiDivider: { styleOverrides: { root: { borderColor: 'rgba(15,23,42,0.07)' } } },
    MuiDialog: { styleOverrides: { paper: { borderRadius: 16, boxShadow: '0 24px 64px rgba(15,23,42,0.18)' } } },
    MuiInputLabel: { styleOverrides: { root: { fontSize: '0.875rem', color: '#64748B' } } },
  },
});

export default theme;
