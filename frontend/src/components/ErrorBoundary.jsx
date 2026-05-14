import React from 'react';

// Catches render-time and lifecycle errors in any descendant. The fallback
// stays styled like the newspaper so a broken widget tree still feels like
// the same site. When a frontend Sentry SDK is wired up, report from
// componentDidCatch — the boundary is already in the right spot.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('homebase: render error', error, info?.componentStack);
  }

  handleReload = () => {
    this.setState({ error: null });
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div
        role="alert"
        style={{
          maxWidth: 480,
          margin: '4rem auto',
          padding: '1.5rem 2rem',
          fontFamily: 'Georgia, serif',
          textAlign: 'center',
          border: '1px solid #ccc',
          background: '#fafaf7',
          color: '#1a1a1a',
        }}
      >
        <h1 style={{ fontSize: '1.5rem', margin: '0 0 0.75rem' }}>
          Something broke in the press room.
        </h1>
        <p style={{ margin: '0 0 1.25rem' }}>
          The page hit an unexpected error. Reload the edition to recover.
        </p>
        <button
          onClick={this.handleReload}
          style={{
            padding: '0.5rem 1.25rem',
            cursor: 'pointer',
            border: '1px solid #333',
            background: 'white',
            font: 'inherit',
          }}
        >
          Reload edition
        </button>
        {import.meta.env.DEV && (
          <pre
            style={{
              marginTop: '1.5rem',
              textAlign: 'left',
              whiteSpace: 'pre-wrap',
              fontSize: '0.75rem',
              color: '#900',
            }}
          >
            {String(this.state.error?.stack || this.state.error)}
          </pre>
        )}
      </div>
    );
  }
}
