import * as React from 'react';

import ConfigStore from 'app/stores/configStore';
import {useLegacyStore} from 'app/stores/useLegacyStore';
import {Config} from 'app/types';
import getDisplayName from 'app/utils/getDisplayName';

type InjectedConfigProps = {
  config: Config;
};

/**
 * Higher order component that passes the config object to the wrapped
 * component
 */
function withConfig<P extends InjectedConfigProps>(
  WrappedComponent: React.ComponentType<P>
) {
  type Props = Omit<P, keyof InjectedConfigProps> & Partial<InjectedConfigProps>;

  const Wrapper: React.FC<Props> = props => {
    const config = useLegacyStore(ConfigStore);
    const allProps = {config, ...props} as P;

    return <WrappedComponent {...allProps} />;
  };

  Wrapper.displayName = `withConfig(${getDisplayName(WrappedComponent)})`;

  return Wrapper;
}

export default withConfig;
