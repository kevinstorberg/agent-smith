import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { SortableHeader } from '../table/SortableHeader';

const column = { ascending: 'name', descending: 'name_desc' } as const;
type Sort = 'manual' | 'name' | 'name_desc';

function Header({
  initial = 'manual',
  onSort = () => undefined,
}: {
  initial?: Sort;
  onSort?: (value: Sort) => void;
}) {
  const [sort, setSort] = useState<Sort>(initial);
  return (
    <table>
      <thead>
        <tr>
          <SortableHeader
            sort={sort}
            column={column}
            onSort={(value) => {
              onSort(value);
              setSort(value);
            }}
          >
            Name
          </SortableHeader>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Example</td>
        </tr>
      </tbody>
    </table>
  );
}

describe('SortableHeader', () => {
  it('uses a scoped native header/button and exposes the accepted direction on the header only', () => {
    render(<Header initial="name" />);
    const header = screen.getByRole('columnheader', { name: 'Name' });
    const button = screen.getByRole('button', { name: 'Name' });
    expect(header.tagName).toBe('TH');
    expect(header).toHaveAttribute('scope', 'col');
    expect(header).toHaveAttribute('aria-sort', 'ascending');
    expect(button).toHaveAttribute('type', 'button');
    expect(button).not.toHaveAttribute('aria-sort');
    expect(button.querySelector('[aria-hidden="true"]')).not.toBeNull();
  });

  it('starts and reverses the same column without maintaining a second sort state', async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(<Header onSort={changed} />);
    const header = screen.getByRole('columnheader');
    expect(header).not.toHaveAttribute('aria-sort');
    await user.click(screen.getByRole('button', { name: 'Name' }));
    expect(changed).toHaveBeenLastCalledWith('name');
    expect(header).toHaveAttribute('aria-sort', 'ascending');
    await user.click(screen.getByRole('button', { name: 'Name' }));
    expect(changed).toHaveBeenLastCalledWith('name_desc');
    expect(header).toHaveAttribute('aria-sort', 'descending');
    expect(changed).toHaveBeenCalledTimes(2);
  });

  it('keeps native Enter/Space activation singular, focused, and outside form submission', async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    const submit = vi.fn((event) => event.preventDefault());
    render(
      <form onSubmit={submit}>
        <Header onSort={changed} />
      </form>,
    );
    await user.tab();
    const button = screen.getByRole('button', { name: 'Name' });
    expect(button).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(changed).toHaveBeenNthCalledWith(1, 'name');
    await user.keyboard(' ');
    expect(changed).toHaveBeenNthCalledWith(2, 'name_desc');
    expect(changed).toHaveBeenCalledTimes(2);
    expect(button).toHaveFocus();
    expect(submit).not.toHaveBeenCalled();
  });

  it('hides stale accepted state but uses the requested direction for the next click', () => {
    const changed = vi.fn();
    render(
      <table>
        <thead>
          <tr>
            <SortableHeader
              sort="name_desc"
              column={column}
              current={false}
              onSort={changed}
            >
              Name
            </SortableHeader>
          </tr>
        </thead>
      </table>,
    );
    expect(screen.getByRole('columnheader')).not.toHaveAttribute('aria-sort');
    const button = screen.getByRole('button', { name: 'Name' });
    expect(button.querySelector('[aria-hidden="true"]')).toHaveTextContent('↕');
    fireEvent.click(button);
    expect(changed).toHaveBeenCalledWith('name');
  });

  it('uses native disabled behavior during the owning controller freeze', async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(
      <table>
        <thead>
          <tr>
            <SortableHeader
              sort="name"
              column={column}
              disabled
              onSort={changed}
            >
              Name
            </SortableHeader>
          </tr>
        </thead>
      </table>,
    );
    const button = screen.getByRole('button', { name: 'Name' });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(changed).not.toHaveBeenCalled();
  });

  it('provides a role-columnheader DIV host without inventing a grid or changing its label', () => {
    const changed = vi.fn();
    render(
      <div role="table">
        <div role="row">
          <SortableHeader
            as="div"
            className="existing-grid-cell"
            sort="name_desc"
            column={column}
            title="Sort by full name"
            onSort={changed}
          >
            Name
          </SortableHeader>
        </div>
      </div>,
    );
    const header = screen.getByRole('columnheader', { name: 'Name' });
    expect(header.tagName).toBe('DIV');
    expect(header).toHaveClass('existing-grid-cell');
    expect(header).toHaveAttribute('aria-sort', 'descending');
    expect(header).not.toHaveAttribute('scope');
    expect(screen.queryByRole('grid')).toBeNull();
    expect(screen.getByRole('button', { name: 'Name' })).toHaveAttribute(
      'title',
      'Sort by full name',
    );
  });

  it('supports an explicit accessible compound sort meaning', () => {
    render(
      <table>
        <thead>
          <tr>
            <SortableHeader
              sort="name"
              column={column}
              ariaLabel="Scores by numeric average"
              onSort={() => undefined}
            >
              Scores
            </SortableHeader>
          </tr>
        </thead>
      </table>,
    );
    expect(
      screen.getByRole('button', { name: 'Scores by numeric average' }),
    ).toHaveTextContent('Scores');
  });
});
